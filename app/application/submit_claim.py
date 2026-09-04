"""Submit claim use case — orchestration and transaction boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from app.application.prior_duplicates import (
    PriorLineAnchor,
    suspected_duplicate_keys_from_prior,
)
from app.domain.accumulators import AccumulatorEntry, AccumulatorKey, AccumulatorScope
from app.domain.engine import (
    AdjudicationContext,
    AdjudicationResult,
    SuspectedDuplicateKey,
    adjudicate,
)
from app.domain.entities import (
    Claim,
    ClaimLine,
    LineDecision,
    Plan,
    Policy,
    ServiceCatalogueEntry,
)
from app.domain.lifecycle import (
    derive_adjudication_state,
    derive_line_state,
    derive_settlement_state,
    payable_from_decisions,
)
from app.domain.money import Money
from app.domain.reasons import ReasonCodeId
from app.domain.rules import Benefit
from app.domain.states import ClaimAdjudicationState, SettlementState
from app.infrastructure.db import SqliteDatabase
from app.infrastructure.mapping import parse_date


class SubmitClaimError(Exception):
    """Claim could not be submitted."""


class MemberNotFoundError(SubmitClaimError):
    """Submitted member_id is not in reference data."""


class ProviderNotFoundError(SubmitClaimError):
    """A line references an unknown provider."""


class PolicyNotFoundError(SubmitClaimError):
    """No unique policy covers all service dates on the claim."""


class PlanNotFoundError(SubmitClaimError):
    """Policy references a plan that is not loaded."""


class AccumulatorLimitExceededError(SubmitClaimError):
    """Pre-commit invariant: a ledger balance would exceed its limit."""


@dataclass(frozen=True, slots=True)
class SubmitClaimResult:
    """Outcome of a synchronous claim submission — states are derived, not stored."""

    claim: Claim
    rejected: bool
    rejection_reason: ReasonCodeId | None
    adjudication_state: ClaimAdjudicationState
    settlement_state: SettlementState
    payable: Money
    line_decisions: tuple[LineDecision, ...]


def submit_claim(db: SqliteDatabase, claim: Claim) -> SubmitClaimResult:
    """Adjudicate and persist a claim atomically."""
    _validate_claim_facts(db, claim)
    db.begin_immediate()
    try:
        policy = _load_policy(db, claim)
        plan = _load_plan(db, policy)
        catalogue = db.catalogue.as_mapping()
        suspected_keys = _load_suspected_duplicate_keys(db, claim.member_id)
        consumed = _load_accumulator_balances(db, claim, plan, catalogue)
        ctx = AdjudicationContext(
            policy=policy,
            plan=plan,
            catalogue=catalogue,
            suspected_duplicate_keys=suspected_keys,
            as_of=claim.submitted_at.date(),
            decided_at=claim.submitted_at,
            accumulator_consumed=consumed,
        )
        result = adjudicate(claim, ctx)
        _persist_submission(db, claim, result)
        _assert_within_limits(
            plan=plan,
            consumed_before=consumed,
            deltas=result.accumulator_deltas,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _build_result(claim, result)


def _validate_claim_facts(db: SqliteDatabase, claim: Claim) -> None:
    if db.members.get(claim.member_id) is None:
        raise MemberNotFoundError(f"member not found: {claim.member_id}")
    for line in claim.lines:
        if line.claim_id != claim.id:
            raise SubmitClaimError(
                f"line {line.id} claim_id {line.claim_id!r} != claim {claim.id!r}"
            )
        if db.providers.get(line.provider_id) is None:
            raise ProviderNotFoundError(
                f"provider not found: {line.provider_id}"
            )


def _policy_covers(policy: Policy, service_date: date) -> bool:
    if service_date < policy.effective_date:
        return False
    if policy.termination_date is not None and service_date > policy.termination_date:
        return False
    return True


def _load_policy(db: SqliteDatabase, claim: Claim) -> Policy:
    eligible = [
        policy
        for policy in db.policies.list_for_member(claim.member_id)
        if all(_policy_covers(policy, line.service_date) for line in claim.lines)
    ]
    if len(eligible) != 1:
        raise PolicyNotFoundError(
            f"expected exactly one policy for member {claim.member_id}, "
            f"found {len(eligible)}"
        )
    return eligible[0]


def _load_plan(db: SqliteDatabase, policy: Policy) -> Plan:
    plan = db.plans.get_latest(policy.plan_id)
    if plan is None:
        raise PlanNotFoundError(f"plan not found: {policy.plan_id}")
    return plan


def _load_suspected_duplicate_keys(
    db: SqliteDatabase, member_id: str
) -> frozenset[SuspectedDuplicateKey]:
    rows = db.connection.execute(
        """
        SELECT c.member_id, cl.provider_id, cl.service_code, cl.service_date, cl.id
        FROM claim_lines cl
        JOIN claims c ON c.id = cl.claim_id
        WHERE c.member_id = ? AND c.rejected = 0
        """,
        (member_id,),
    ).fetchall()
    anchors: list[PriorLineAnchor] = []
    for row in rows:
        decision = db.decisions.current_for_line(row["id"])
        if decision is None:
            continue
        has_open_dispute = bool(db.disputes.list_open_for_line(row["id"]))
        anchors.append(
            PriorLineAnchor(
                member_id=row["member_id"],
                provider_id=row["provider_id"],
                service_code=row["service_code"],
                service_date=parse_date(row["service_date"]),
                line_state=derive_line_state(
                    decision, has_open_dispute=has_open_dispute
                ),
            )
        )
    return suspected_duplicate_keys_from_prior(anchors)


def _benefit_for_code(plan: Plan, benefit_code: str) -> Benefit | None:
    for benefit in plan.benefits:
        if benefit.code == benefit_code:
            return benefit
    return None


def _accumulator_keys_for_claim(
    claim: Claim,
    plan: Plan,
    catalogue: Mapping[str, ServiceCatalogueEntry],
) -> set[AccumulatorKey]:
    keys: set[AccumulatorKey] = set()
    for line in claim.lines:
        keys.add(
            AccumulatorKey(
                member_id=claim.member_id,
                plan_year=line.service_date.year,
                scope=AccumulatorScope.DEDUCTIBLE,
                benefit_code=None,
            )
        )
        entry = catalogue.get(line.service_code)
        if entry is None:
            continue
        benefit = _benefit_for_code(plan, entry.benefit_code)
        if benefit is None:
            continue
        if benefit.annual_limit_amount is not None:
            keys.add(
                AccumulatorKey(
                    member_id=claim.member_id,
                    plan_year=line.service_date.year,
                    scope=AccumulatorScope.BENEFIT_AMOUNT,
                    benefit_code=benefit.code,
                )
            )
        if benefit.annual_visit_limit is not None:
            keys.add(
                AccumulatorKey(
                    member_id=claim.member_id,
                    plan_year=line.service_date.year,
                    scope=AccumulatorScope.BENEFIT_VISITS,
                    benefit_code=benefit.code,
                )
            )
    return keys


def _load_accumulator_balances(
    db: SqliteDatabase,
    claim: Claim,
    plan: Plan,
    catalogue: Mapping[str, ServiceCatalogueEntry],
) -> dict[AccumulatorKey, int]:
    keys = _accumulator_keys_for_claim(claim, plan, catalogue)
    return {key: db.accumulators.balance(key) for key in keys}


def _persist_submission(
    db: SqliteDatabase, claim: Claim, result: AdjudicationResult
) -> None:
    db.claims.add(claim, rejected=result.rejected)
    if result.rejected:
        return
    for line_result in result.line_results:
        if line_result.decision is not None:
            db.decisions.add(line_result.decision)
    for entry in result.accumulator_deltas:
        db.accumulators.add(entry)


def _assert_within_limits(
    *,
    plan: Plan,
    consumed_before: Mapping[AccumulatorKey, int],
    deltas: tuple[AccumulatorEntry, ...],
) -> None:
    balances = dict(consumed_before)
    for entry in deltas:
        balances[entry.key] = balances.get(entry.key, 0) + entry.quantity
    for key, balance in balances.items():
        if key.scope is AccumulatorScope.DEDUCTIBLE:
            if balance > plan.deductible.minor_units:
                raise AccumulatorLimitExceededError(
                    f"deductible balance {balance} exceeds limit "
                    f"{plan.deductible.minor_units}"
                )
            continue
        benefit = _benefit_for_code(plan, key.benefit_code or "")
        if benefit is None:
            continue
        if key.scope is AccumulatorScope.BENEFIT_AMOUNT:
            limit = benefit.annual_limit_amount
            if limit is not None and balance > limit.minor_units:
                raise AccumulatorLimitExceededError(
                    f"benefit amount balance {balance} exceeds limit "
                    f"{limit.minor_units} for {benefit.code}"
                )
        elif key.scope is AccumulatorScope.BENEFIT_VISITS:
            limit = benefit.annual_visit_limit
            if limit is not None and balance > limit:
                raise AccumulatorLimitExceededError(
                    f"visit balance {balance} exceeds limit {limit} "
                    f"for {benefit.code}"
                )


def _build_result(claim: Claim, result: AdjudicationResult) -> SubmitClaimResult:
    if result.rejected:
        return SubmitClaimResult(
            claim=claim,
            rejected=True,
            rejection_reason=result.rejection_reason,
            adjudication_state=ClaimAdjudicationState.REJECTED,
            settlement_state=SettlementState.NOTHING_DUE,
            payable=Money.zero(),
            line_decisions=(),
        )
    decisions = tuple(
        line_result.decision
        for line_result in sorted(
            result.line_results, key=lambda item: item.line_number
        )
        if line_result.decision is not None
    )
    line_states = tuple(
        derive_line_state(decision) for decision in decisions
    )
    payable = payable_from_decisions(decisions)
    return SubmitClaimResult(
        claim=claim,
        rejected=False,
        rejection_reason=None,
        adjudication_state=derive_adjudication_state(
            rejected=False, line_states=line_states
        ),
        settlement_state=derive_settlement_state(payable, Money.zero()),
        payable=payable,
        line_decisions=decisions,
    )
