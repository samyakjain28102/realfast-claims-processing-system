"""Adjudication engine — pure function, gates 0–6 in this slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping

from app.domain.entities import (
    Claim,
    ClaimLine,
    LineDecision,
    Plan,
    Policy,
    ServiceCatalogueEntry,
    TraceStep,
)
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


@dataclass(frozen=True, slots=True)
class LineAdjudicationResult:
    line_id: str
    line_number: int
    decision: LineDecision | None
    cleared_for_pricing: bool


@dataclass(frozen=True, slots=True)
class AdjudicationResult:
    rejected: bool
    rejection_reason: ReasonCodeId | None
    line_results: tuple[LineAdjudicationResult, ...]


def adjudicate(claim: Claim, ctx: AdjudicationContext) -> AdjudicationResult:
    """Apply gates 0–6. Lines cleared for pricing await gates 7–9 in a later slice."""
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

    for line in lines:
        decision = _adjudicate_line(
            claim=claim,
            line=line,
            ctx=ctx,
            seen_confirmed_keys=seen_confirmed_keys,
        )
        if decision is None:
            line_results.append(
                LineAdjudicationResult(
                    line_id=line.id,
                    line_number=line.line_number,
                    decision=None,
                    cleared_for_pricing=True,
                )
            )
        else:
            line_results.append(
                LineAdjudicationResult(
                    line_id=line.id,
                    line_number=line.line_number,
                    decision=decision,
                    cleared_for_pricing=False,
                )
            )

    return AdjudicationResult(
        rejected=False,
        rejection_reason=None,
        line_results=tuple(line_results),
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
) -> LineDecision | None:
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

    return None


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
) -> TraceStep:
    return TraceStep(
        step=step,
        rule=rule,
        plan_version=plan_version,
        inputs=inputs,
        result=result,
    )


def _line_decision(
    *,
    claim: Claim,
    line: ClaimLine,
    ctx: AdjudicationContext,
    outcome: LineOutcome,
    reason: ReasonCodeId,
    trace: list[TraceStep],
) -> LineDecision:
    return LineDecision(
        id=f"{claim.id}:{line.id}:1",
        line_id=line.id,
        sequence=1,
        source=DecisionSource.RULES,
        outcome=outcome,
        reasons=(reason,),
        trace=tuple(trace),
        plan_version=ctx.plan.version,
        decided_at=ctx.decided_at,
        decided_by=ctx.decided_by,
        amounts=None,
    )
