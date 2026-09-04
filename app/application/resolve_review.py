"""Resolve a NEEDS_REVIEW line or an open dispute by re-adjudicating the claim."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from app.application.submit_claim import (
    PlanNotFoundError,
    _accumulator_keys_for_claim,
    _assert_within_limits,
    _build_result,
    _load_accumulator_balances,
    _load_policy,
    _load_suspected_duplicate_keys,
    _validate_claim_facts,
)
from app.domain.accumulators import AccumulatorEntry, compensating_entry
from app.domain.engine import AdjudicationContext, AdjudicationResult, adjudicate
from app.domain.entities import (
    Claim,
    ClaimLine,
    LineDecision,
    LineFactCorrections,
    ReviewResolution,
)
from app.domain.lifecycle import derive_line_state
from app.domain.money import Money
from app.domain.states import (
    ClaimAdjudicationState,
    DisputeState,
    LineOutcome,
    LineState,
    ReviewResolutionMode,
    SettlementState,
)
from app.infrastructure.db import SqliteDatabase


class ResolveReviewError(Exception):
    """Review could not be resolved."""


class LineNotFoundError(ResolveReviewError):
    """line_id does not exist."""


class LineNotInReviewError(ResolveReviewError):
    """Line is not NEEDS_REVIEW or UNDER_APPEAL."""


class UpholdNotAllowedError(ResolveReviewError):
    """Uphold is valid only when an open dispute exists on the line (D28)."""


class InvalidResolveRequestError(ResolveReviewError):
    """Mode and corrections are inconsistent."""


class InvalidCorrectionError(ResolveReviewError):
    """Corrected facts would make the claim structurally invalid."""


@dataclass(frozen=True, slots=True)
class ResolveReviewResult:
    """Outcome of one resolution attempt — states remain derived."""

    claim: Claim
    adjudication_state: ClaimAdjudicationState
    settlement_state: SettlementState
    payable: Money
    line_decisions: tuple[LineDecision, ...]
    resolution: ReviewResolution


def resolve_review(
    db: SqliteDatabase,
    *,
    line_id: str,
    mode: ReviewResolutionMode,
    reviewer_id: str,
    note: str,
    corrections: LineFactCorrections | None = None,
    decided_at: datetime | None = None,
) -> ResolveReviewResult:
    """Correct facts or uphold a dispute, then re-adjudicate the whole claim."""
    _validate_request(mode, corrections)
    stored = db.claims.find_by_line_id(line_id)
    if stored is None:
        raise LineNotFoundError(line_id)
    if stored.rejected:
        raise LineNotInReviewError(line_id)

    current_decision = db.decisions.current_for_line(line_id)
    open_disputes = db.disputes.list_open_for_line(line_id)
    line_state = derive_line_state(
        current_decision, has_open_dispute=bool(open_disputes)
    )
    if line_state not in {LineState.NEEDS_REVIEW, LineState.UNDER_APPEAL}:
        raise LineNotInReviewError(line_id)
    if mode is ReviewResolutionMode.UPHOLD and not open_disputes:
        raise UpholdNotAllowedError(line_id)

    original_claim = stored.claim
    working_claim = (
        original_claim
        if corrections is None
        else _apply_corrections(original_claim, line_id, corrections)
    )
    _validate_claim_facts(db, working_claim)

    decided_at = decided_at or datetime.now()
    target_dispute = open_disputes[0] if open_disputes else None
    closing_line_id = line_id if target_dispute is not None else None

    db.begin_immediate()
    try:
        policy = _load_policy(db, original_claim)
        plan_version = _original_plan_version(db, original_claim.id)
        plan = db.plans.get(policy.plan_id, plan_version)
        if plan is None:
            raise PlanNotFoundError(
                f"plan {policy.plan_id} version {plan_version} not found"
            )
        catalogue = db.catalogue.as_mapping()
        to_reverse = _unreversed_original_entries(db, original_claim.id)
        consumed = _starting_balances(
            db, working_claim, plan, catalogue, to_reverse
        )
        suspected_keys = _load_suspected_duplicate_keys(
            db, working_claim.member_id, exclude_claim_id=original_claim.id
        )
        ctx = AdjudicationContext(
            policy=policy,
            plan=plan,
            catalogue=catalogue,
            suspected_duplicate_keys=suspected_keys,
            as_of=original_claim.submitted_at.date(),
            decided_at=decided_at,
            accumulator_consumed=consumed,
        )
        result = adjudicate(working_claim, ctx)
        if result.rejected:
            raise InvalidCorrectionError(original_claim.id)

        current_by_line: dict[str, LineDecision] = {}
        for line in original_claim.lines:
            existing = db.decisions.current_for_line(line.id)
            if existing is None:
                raise LineNotInReviewError(line_id)
            current_by_line[line.id] = existing
        new_decisions, reminted_deltas = _assign_sequences(
            result, current_by_line
        )
        new_by_line = {decision.line_id: decision for decision in new_decisions}
        old_decision_line = {
            decision.id: decision.line_id
            for line in original_claim.lines
            for decision in db.decisions.list_for_line(line.id)
        }
        reversals = tuple(
            compensating_entry(
                entry,
                id=f"{new_by_line[old_decision_line[entry.decision_id]].id}"
                f":REV:{entry.id}",
                decision_id=new_by_line[old_decision_line[entry.decision_id]].id,
            )
            for entry in to_reverse
        )
        posted = _postable_deltas(
            reminted_deltas,
            new_by_line=new_by_line,
            db=db,
            closing_line_id=closing_line_id,
        )
        if corrections is not None:
            db.claims.update_line_facts(line_id, corrections)
        for decision in new_decisions:
            db.decisions.add(decision)
        for entry in reversals:
            db.accumulators.add(entry)
        for entry in posted:
            db.accumulators.add(entry)

        resulting = new_by_line[line_id]
        resolution = ReviewResolution(
            id=f"{line_id}:R{len(db.reviews.list_for_line(line_id)) + 1}",
            line_id=line_id,
            mode=mode,
            reviewer_id=reviewer_id,
            note=note,
            resulting_decision_id=resulting.id,
            dispute_id=None if target_dispute is None else target_dispute.id,
            corrections=corrections,
        )
        db.reviews.add(resolution)
        if target_dispute is not None:
            db.disputes.set_state(target_dispute.id, DisputeState.CLOSED)

        keys = _accumulator_keys_for_claim(working_claim, plan, catalogue)
        for entry in (*reversals, *posted):
            keys.add(entry.key)
        raw = {key: db.accumulators.balance(key) for key in keys}
        # Reversals and new posts are already in the ledger at this point, so
        # the closing invariant is the committed balances themselves.
        _assert_within_limits(
            plan=plan,
            consumed_before=raw,
            deltas=(),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    refreshed = db.claims.get(original_claim.id)
    assert refreshed is not None
    built = _build_result(refreshed.claim, result)
    return ResolveReviewResult(
        claim=refreshed.claim,
        adjudication_state=built.adjudication_state,
        settlement_state=built.settlement_state,
        payable=built.payable,
        line_decisions=tuple(
            new_by_line[line.id] for line in refreshed.claim.lines
        ),
        resolution=resolution,
    )


def _validate_request(
    mode: ReviewResolutionMode, corrections: LineFactCorrections | None
) -> None:
    if mode is ReviewResolutionMode.CORRECT_FACTS and corrections is None:
        raise InvalidResolveRequestError("correct_facts requires corrections")
    if mode is ReviewResolutionMode.UPHOLD and corrections is not None:
        raise InvalidResolveRequestError("uphold must not include corrections")


def _apply_corrections(
    claim: Claim, line_id: str, corrections: LineFactCorrections
) -> Claim:
    lines: list[ClaimLine] = []
    for line in claim.lines:
        if line.id != line_id:
            lines.append(line)
            continue
        lines.append(
            replace(
                line,
                service_code=(
                    line.service_code
                    if corrections.service_code is None
                    else corrections.service_code
                ),
                service_date=(
                    line.service_date
                    if corrections.service_date is None
                    else corrections.service_date
                ),
                provider_id=(
                    line.provider_id
                    if corrections.provider_id is None
                    else corrections.provider_id
                ),
                billed_amount=(
                    line.billed_amount
                    if corrections.billed_amount is None
                    else corrections.billed_amount
                ),
                diagnosis_code=(
                    line.diagnosis_code
                    if corrections.diagnosis_code is None
                    else corrections.diagnosis_code
                ),
            )
        )
    return replace(claim, lines=tuple(lines))


def _original_plan_version(db: SqliteDatabase, claim_id: str) -> int:
    first_pass = [
        decision
        for decision in db.decisions.list_for_claim(claim_id)
        if decision.sequence == 1
    ]
    versions = {decision.plan_version for decision in first_pass}
    if len(versions) != 1:
        raise InvalidCorrectionError(claim_id)
    return versions.pop()


def _unreversed_original_entries(
    db: SqliteDatabase, claim_id: str
) -> tuple[AccumulatorEntry, ...]:
    found: list[AccumulatorEntry] = []
    for decision in db.decisions.list_for_claim(claim_id):
        for entry in db.accumulators.list_for_decision(decision.id):
            if entry.reverses_entry_id is not None:
                continue
            if db.accumulators.is_reversed(entry.id):
                continue
            found.append(entry)
    return tuple(found)


def _starting_balances(
    db: SqliteDatabase,
    claim: Claim,
    plan,
    catalogue,
    to_reverse: tuple[AccumulatorEntry, ...],
) -> dict:
    consumed = dict(_load_accumulator_balances(db, claim, plan, catalogue))
    for entry in to_reverse:
        if entry.key not in consumed:
            consumed[entry.key] = db.accumulators.balance(entry.key)
        consumed[entry.key] -= entry.quantity
        if consumed[entry.key] < 0:
            raise ResolveReviewError(
                f"ledger snapshot for {entry.key} would be negative"
            )
    return consumed


def _assign_sequences(
    result: AdjudicationResult,
    current_by_line: dict[str, LineDecision],
) -> tuple[tuple[LineDecision, ...], tuple[AccumulatorEntry, ...]]:
    decisions: list[LineDecision] = []
    id_map: dict[str, str] = {}
    for line_result in result.line_results:
        decision = line_result.decision
        if decision is None:
            continue
        previous = current_by_line[decision.line_id]
        sequence = previous.sequence + 1
        new_id = f"{decision.line_id}:{sequence}"
        reminted = replace(decision, id=new_id, sequence=sequence)
        id_map[decision.id] = reminted.id
        decisions.append(reminted)
    reminted_deltas = tuple(
        replace(
            entry,
            id=f"{id_map[entry.decision_id]}:{entry.key.scope.value}",
            decision_id=id_map[entry.decision_id],
        )
        for entry in result.accumulator_deltas
    )
    return tuple(decisions), reminted_deltas


def _postable_deltas(
    deltas: tuple[AccumulatorEntry, ...],
    *,
    new_by_line: dict[str, LineDecision],
    db: SqliteDatabase,
    closing_line_id: str | None,
) -> tuple[AccumulatorEntry, ...]:
    new_by_id = {decision.id: decision for decision in new_by_line.values()}
    posted: list[AccumulatorEntry] = []
    for entry in deltas:
        decision = new_by_id[entry.decision_id]
        if decision.outcome is LineOutcome.NEEDS_REVIEW:
            continue
        if decision.line_id != closing_line_id and db.disputes.list_open_for_line(
            decision.line_id
        ):
            continue
        posted.append(entry)
    return tuple(posted)
