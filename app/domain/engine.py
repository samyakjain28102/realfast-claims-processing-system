"""Adjudication engine — pure function, gates 0–7 plus deductible."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Mapping

from app.domain.accumulators import (
    AccumulatorEntry,
    AccumulatorKey,
    AccumulatorScope,
    apply_quantity,
)
from app.domain.entities import (
    Claim,
    ClaimLine,
    DecisionAmounts,
    LineDecision,
    Plan,
    Policy,
    ServiceCatalogueEntry,
    TraceStep,
)
from app.domain.money import Money
from app.domain.reasons import ReasonCodeId
from app.domain.rules import Benefit
from app.domain.states import DecisionSource, LineOutcome


@dataclass(frozen=True, slots=True)
class SuspectedDuplicateKey:
    """Cross-claim duplicate match key (D17) — billed amount excluded."""

    member_id: str
    provider_id: str
    service_code: str
    service_date: date


@dataclass(frozen=True, slots=True)
class AdjudicationContext:
    """Snapshot of everything needed to adjudicate a claim without I/O."""

    policy: Policy
    plan: Plan
    catalogue: Mapping[str, ServiceCatalogueEntry]
    suspected_duplicate_keys: frozenset[SuspectedDuplicateKey]
    as_of: date
    decided_at: datetime
    decided_by: str = "rules"
    accumulator_consumed: Mapping[AccumulatorKey, int] = field(default_factory=dict)

    def scheduled_amount_for(self, service_code: str) -> Money | None:
        """Look up the plan fee-schedule amount for a service, if one exists."""
        entry = self.catalogue.get(service_code)
        if entry is None:
            return None
        return entry.scheduled_amount


@dataclass(frozen=True, slots=True)
class LinePricing:
    """Gate 7 amounts. Deductible, limits, and payment are not applied yet."""

    allowed: Money
    above_allowed: Money
    scheduled_amount: Money
    trace: TraceStep


@dataclass(frozen=True, slots=True)
class DeductibleComputation:
    """Gate 9 deductible split. Annual limits and payment are not applied yet."""

    applied: Money
    remaining_before: Money
    remaining_after: Money
    after_deductible: Money
    trace: TraceStep


@dataclass(frozen=True, slots=True)
class LineAdjudicationResult:
    line_id: str
    line_number: int
    decision: LineDecision | None
    cleared_for_pricing: bool
    pricing: LinePricing | None = None
    deductible: DeductibleComputation | None = None


@dataclass(frozen=True, slots=True)
class AdjudicationResult:
    rejected: bool
    rejection_reason: ReasonCodeId | None
    line_results: tuple[LineAdjudicationResult, ...]
    accumulator_deltas: tuple[AccumulatorEntry, ...] = ()


def adjudicate(claim: Claim, ctx: AdjudicationContext) -> AdjudicationResult:
    """Apply gates 0–7 and deductible. Limits await a later slice."""
    rejection = _validate_claim_structure(claim, ctx)
    if rejection is not None:
        return AdjudicationResult(
            rejected=True,
            rejection_reason=rejection,
            line_results=(),
        )

    lines = tuple(sorted(claim.lines, key=lambda line: line.line_number))
    seen_confirmed_keys: set[tuple[str, date, str]] = set()
    line_results: list[LineAdjudicationResult] = []
    working_consumed: dict[AccumulatorKey, int] = dict(ctx.accumulator_consumed)
    deltas: list[AccumulatorEntry] = []

    for line in lines:
        line_eval = _adjudicate_line(
            claim=claim,
            line=line,
            ctx=ctx,
            seen_confirmed_keys=seen_confirmed_keys,
        )
        if isinstance(line_eval, LinePricing):
            deductible, decision, new_entries = _apply_deductible(
                claim=claim,
                line=line,
                ctx=ctx,
                pricing=line_eval,
                working_consumed=working_consumed,
            )
            deltas.extend(new_entries)
            line_results.append(
                LineAdjudicationResult(
                    line_id=line.id,
                    line_number=line.line_number,
                    decision=decision,
                    cleared_for_pricing=decision is None,
                    pricing=line_eval,
                    deductible=deductible,
                )
            )
        else:
            line_results.append(
                LineAdjudicationResult(
                    line_id=line.id,
                    line_number=line.line_number,
                    decision=line_eval,
                    cleared_for_pricing=False,
                )
            )

    return AdjudicationResult(
        rejected=False,
        rejection_reason=None,
        line_results=tuple(line_results),
        accumulator_deltas=tuple(deltas),
    )


def _validate_claim_structure(
    claim: Claim,
    ctx: AdjudicationContext,
) -> ReasonCodeId | None:
    if not claim.lines:
        return ReasonCodeId.REJ_INVALID_CLAIM
    if claim.member_id != ctx.policy.member_id:
        return ReasonCodeId.REJ_INVALID_CLAIM
    if ctx.policy.plan_id != ctx.plan.id:
        return ReasonCodeId.REJ_INVALID_CLAIM
    for line in claim.lines:
        if line.claim_id != claim.id:
            return ReasonCodeId.REJ_INVALID_CLAIM
        if line.service_date > ctx.as_of:
            return ReasonCodeId.REJ_INVALID_CLAIM
    return None


def _confirmed_duplicate_key(line: ClaimLine) -> tuple[str, date, str]:
    return (line.service_code, line.service_date, line.provider_id)


def _suspected_duplicate_key(claim: Claim, line: ClaimLine) -> SuspectedDuplicateKey:
    return SuspectedDuplicateKey(
        member_id=claim.member_id,
        provider_id=line.provider_id,
        service_code=line.service_code,
        service_date=line.service_date,
    )


def _adjudicate_line(
    *,
    claim: Claim,
    line: ClaimLine,
    ctx: AdjudicationContext,
    seen_confirmed_keys: set[tuple[str, date, str]],
) -> LineDecision | LinePricing:
    trace: list[TraceStep] = []
    plan_version = ctx.plan.version

    # Gate 1 — service catalogue
    catalogue_entry = ctx.catalogue.get(line.service_code)
    if catalogue_entry is None:
        trace.append(
            _trace_step(
                step="service_catalogue",
                rule="SERVICE_CATALOGUE",
                plan_version=plan_version,
                inputs={"service_code": line.service_code},
                result="unknown",
            )
        )
        return _line_decision(
            claim=claim,
            line=line,
            ctx=ctx,
            outcome=LineOutcome.NEEDS_REVIEW,
            reason=ReasonCodeId.REV_UNKNOWN_SERVICE,
            trace=trace,
        )
    trace.append(
        _trace_step(
            step="service_catalogue",
            rule="SERVICE_CATALOGUE",
            plan_version=plan_version,
            inputs={"service_code": line.service_code},
            result="pass",
        )
    )

    # Gate 2 — confirmed duplicate within claim
    confirmed_key = _confirmed_duplicate_key(line)
    if confirmed_key in seen_confirmed_keys:
        trace.append(
            _trace_step(
                step="confirmed_duplicate",
                rule="CLAIM.duplicate_line",
                plan_version=plan_version,
                inputs={
                    "service_code": line.service_code,
                    "service_date": line.service_date.isoformat(),
                    "provider_id": line.provider_id,
                },
                result="duplicate",
            )
        )
        return _line_decision(
            claim=claim,
            line=line,
            ctx=ctx,
            outcome=LineOutcome.DENIED,
            reason=ReasonCodeId.DEN_DUPLICATE,
            trace=trace,
        )
    trace.append(
        _trace_step(
            step="confirmed_duplicate",
            rule="CLAIM.duplicate_line",
            plan_version=plan_version,
            inputs={
                "service_code": line.service_code,
                "service_date": line.service_date.isoformat(),
                "provider_id": line.provider_id,
            },
            result="pass",
        )
    )
    seen_confirmed_keys.add(confirmed_key)

    # Gate 3 — suspected duplicate from prior claims
    suspected_key = _suspected_duplicate_key(claim, line)
    if suspected_key in ctx.suspected_duplicate_keys:
        trace.append(
            _trace_step(
                step="suspected_duplicate",
                rule="PRIOR_CLAIM.duplicate_line",
                plan_version=plan_version,
                inputs={
                    "member_id": claim.member_id,
                    "provider_id": line.provider_id,
                    "service_code": line.service_code,
                    "service_date": line.service_date.isoformat(),
                },
                result="suspected",
            )
        )
        return _line_decision(
            claim=claim,
            line=line,
            ctx=ctx,
            outcome=LineOutcome.NEEDS_REVIEW,
            reason=ReasonCodeId.REV_SUSPECTED_DUPLICATE,
            trace=trace,
        )
    trace.append(
        _trace_step(
            step="suspected_duplicate",
            rule="PRIOR_CLAIM.duplicate_line",
            plan_version=plan_version,
            inputs={
                "member_id": claim.member_id,
                "provider_id": line.provider_id,
                "service_code": line.service_code,
                "service_date": line.service_date.isoformat(),
            },
            result="pass",
        )
    )

    # Gate 4 — policy eligibility on service date
    if not _policy_active_on(ctx.policy, line.service_date):
        trace.append(
            _trace_step(
                step="eligibility",
                rule="POLICY.active_on_service_date",
                plan_version=plan_version,
                inputs={
                    "service_date": line.service_date.isoformat(),
                    "effective_date": ctx.policy.effective_date.isoformat(),
                    "termination_date": (
                        ctx.policy.termination_date.isoformat()
                        if ctx.policy.termination_date
                        else None
                    ),
                },
                result="inactive",
            )
        )
        return _line_decision(
            claim=claim,
            line=line,
            ctx=ctx,
            outcome=LineOutcome.DENIED,
            reason=ReasonCodeId.DEN_NOT_ELIGIBLE,
            trace=trace,
        )
    trace.append(
        _trace_step(
            step="eligibility",
            rule="POLICY.active_on_service_date",
            plan_version=plan_version,
            inputs={"service_date": line.service_date.isoformat()},
            result="pass",
        )
    )

    benefit = _benefit_for_entry(ctx.plan, catalogue_entry)

    # Gate 5 — benefit covered
    if benefit is None:
        trace.append(
            _trace_step(
                step="coverage",
                rule=f"BENEFIT.{catalogue_entry.benefit_code}",
                plan_version=plan_version,
                inputs={"benefit_code": catalogue_entry.benefit_code},
                result="unknown",
            )
        )
        return _line_decision(
            claim=claim,
            line=line,
            ctx=ctx,
            outcome=LineOutcome.NEEDS_REVIEW,
            reason=ReasonCodeId.REV_UNKNOWN_BENEFIT,
            trace=trace,
        )
    if not benefit.covered:
        trace.append(
            _trace_step(
                step="coverage",
                rule=f"BENEFIT.{benefit.code}.covered",
                plan_version=plan_version,
                inputs={"benefit_code": benefit.code},
                result="not_covered",
            )
        )
        return _line_decision(
            claim=claim,
            line=line,
            ctx=ctx,
            outcome=LineOutcome.DENIED,
            reason=ReasonCodeId.DEN_NOT_COVERED,
            trace=trace,
        )
    trace.append(
        _trace_step(
            step="coverage",
            rule=f"BENEFIT.{benefit.code}.covered",
            plan_version=plan_version,
            inputs={"benefit_code": benefit.code},
            result="pass",
        )
    )

    # Gate 6 — explicit exclusion
    if benefit.excluded:
        trace.append(
            _trace_step(
                step="exclusion",
                rule=f"BENEFIT.{benefit.code}.excluded",
                plan_version=plan_version,
                inputs={"benefit_code": benefit.code},
                result="excluded",
            )
        )
        return _line_decision(
            claim=claim,
            line=line,
            ctx=ctx,
            outcome=LineOutcome.DENIED,
            reason=ReasonCodeId.DEN_EXCLUDED,
            trace=trace,
        )
    trace.append(
        _trace_step(
            step="exclusion",
            rule=f"BENEFIT.{benefit.code}.excluded",
            plan_version=plan_version,
            inputs={"benefit_code": benefit.code},
            result="pass",
        )
    )

    # Gate 7 — fee schedule / allowed amount
    scheduled_amount = ctx.scheduled_amount_for(line.service_code)
    if scheduled_amount is None:
        trace.append(
            _trace_step(
                step="pricing",
                rule="FEE_SCHEDULE.scheduled_amount",
                plan_version=plan_version,
                inputs={"service_code": line.service_code},
                result="no_price",
            )
        )
        return _line_decision(
            claim=claim,
            line=line,
            ctx=ctx,
            outcome=LineOutcome.NEEDS_REVIEW,
            reason=ReasonCodeId.REV_NO_PRICE,
            trace=trace,
        )

    allowed = Money.minimum(line.billed_amount, scheduled_amount)
    above_allowed = line.billed_amount - allowed
    pricing_step = _trace_step(
        step="pricing",
        rule="FEE_SCHEDULE.scheduled_amount",
        plan_version=plan_version,
        inputs={
            "service_code": line.service_code,
            "billed_amount": line.billed_amount.minor_units,
            "scheduled_amount": scheduled_amount.minor_units,
            "allowed": allowed.minor_units,
            "above_allowed": above_allowed.minor_units,
        },
        result="pass",
    )
    return LinePricing(
        allowed=allowed,
        above_allowed=above_allowed,
        scheduled_amount=scheduled_amount,
        trace=pricing_step,
    )


def _deductible_key(member_id: str, service_date: date) -> AccumulatorKey:
    return AccumulatorKey(
        member_id=member_id,
        plan_year=service_date.year,
        scope=AccumulatorScope.DEDUCTIBLE,
        benefit_code=None,
    )


def _apply_deductible(
    *,
    claim: Claim,
    line: ClaimLine,
    ctx: AdjudicationContext,
    pricing: LinePricing,
    working_consumed: dict[AccumulatorKey, int],
) -> tuple[DeductibleComputation, LineDecision | None, tuple[AccumulatorEntry, ...]]:
    key = _deductible_key(claim.member_id, line.service_date)
    consumed = working_consumed.get(key, 0)
    applied_units, consumed_after = apply_quantity(
        limit=ctx.plan.deductible.minor_units,
        consumed=consumed,
        requested=pricing.allowed.minor_units,
    )
    working_consumed[key] = consumed_after
    remaining_before = max(0, ctx.plan.deductible.minor_units - consumed)
    remaining_after = max(0, ctx.plan.deductible.minor_units - consumed_after)
    after_units = pricing.allowed.minor_units - applied_units

    if applied_units == 0:
        deductible_result = "met"
    elif after_units == 0:
        deductible_result = "absorbed"
    else:
        deductible_result = "partial"

    deductible_step = _trace_step(
        step="deductible",
        rule="PLAN.deductible",
        plan_version=ctx.plan.version,
        inputs={
            "allowed": pricing.allowed.minor_units,
            "deductible_limit": ctx.plan.deductible.minor_units,
            "deductible_remaining": remaining_before,
            "deductible_applied": applied_units,
        },
        result=deductible_result,
        accumulator_before=consumed,
        accumulator_after=consumed_after,
    )
    deductible = DeductibleComputation(
        applied=Money(applied_units),
        remaining_before=Money(remaining_before),
        remaining_after=Money(remaining_after),
        after_deductible=Money(after_units),
        trace=deductible_step,
    )

    # Zero allowed is not "absorbed by deductible"; do not invent APPROVED.
    if after_units != 0 or pricing.allowed.minor_units == 0:
        return deductible, None, ()

    reasons: list[ReasonCodeId] = []
    if pricing.above_allowed.minor_units > 0:
        reasons.append(ReasonCodeId.MEM_ABOVE_ALLOWED)
    reasons.append(ReasonCodeId.MEM_DEDUCTIBLE)
    amounts = DecisionAmounts(
        allowed=pricing.allowed,
        above_allowed=pricing.above_allowed,
        deductible_applied=Money(applied_units),
        plan_paid=Money.zero(),
        denied_amount=Money.zero(),
    )
    amounts.check_conservation(line.billed_amount)
    decision = _line_decision(
        claim=claim,
        line=line,
        ctx=ctx,
        outcome=LineOutcome.APPROVED,
        reasons=tuple(reasons),
        trace=[pricing.trace, deductible_step],
        amounts=amounts,
    )
    entries: tuple[AccumulatorEntry, ...] = ()
    if applied_units > 0:
        entries = (
            AccumulatorEntry(
                id=f"{decision.id}:DEDUCTIBLE",
                key=key,
                quantity=applied_units,
                decision_id=decision.id,
            ),
        )
    return deductible, decision, entries


def _policy_active_on(policy: Policy, service_date: date) -> bool:
    if service_date < policy.effective_date:
        return False
    if policy.termination_date is not None and service_date > policy.termination_date:
        return False
    return True


def _benefit_for_entry(plan: Plan, entry: ServiceCatalogueEntry) -> Benefit | None:
    for benefit in plan.benefits:
        if benefit.code == entry.benefit_code:
            return benefit
    return None


def _trace_step(
    *,
    step: str,
    rule: str,
    plan_version: int,
    inputs: dict[str, object],
    result: str,
    accumulator_before: int | None = None,
    accumulator_after: int | None = None,
) -> TraceStep:
    return TraceStep(
        step=step,
        rule=rule,
        plan_version=plan_version,
        inputs=inputs,
        result=result,
        accumulator_before=accumulator_before,
        accumulator_after=accumulator_after,
    )


def _line_decision(
    *,
    claim: Claim,
    line: ClaimLine,
    ctx: AdjudicationContext,
    outcome: LineOutcome,
    trace: list[TraceStep],
    reason: ReasonCodeId | None = None,
    reasons: tuple[ReasonCodeId, ...] | None = None,
    amounts: DecisionAmounts | None = None,
) -> LineDecision:
    resolved = reasons if reasons is not None else (reason,) if reason is not None else ()
    return LineDecision(
        id=f"{claim.id}:{line.id}:1",
        line_id=line.id,
        sequence=1,
        source=DecisionSource.RULES,
        outcome=outcome,
        reasons=resolved,
        trace=tuple(trace),
        plan_version=ctx.plan.version,
        decided_at=ctx.decided_at,
        decided_by=ctx.decided_by,
        amounts=amounts,
    )
