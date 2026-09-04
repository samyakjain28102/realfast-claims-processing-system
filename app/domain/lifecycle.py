"""Derived line and claim lifecycles — recomputed, never stored."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.domain.entities import DecisionAmounts, LineDecision, Payment
from app.domain.money import Money
from app.domain.states import (
    ClaimAdjudicationState,
    LineOutcome,
    LineState,
    SettlementState,
)


def line_outcome_from_amounts(amounts: DecisionAmounts) -> LineOutcome:
    """Coverage determination from the financial split.

    The whole allowed amount can land on the deductible: that is APPROVED
    with plan_paid = 0, not a denial.
    """
    if amounts.denied_amount.minor_units == 0:
        return LineOutcome.APPROVED
    covered = (
        amounts.deductible_applied.minor_units + amounts.plan_paid.minor_units
    )
    if covered > 0:
        return LineOutcome.PARTIALLY_APPROVED
    return LineOutcome.DENIED


def derive_line_state(
    decision: LineDecision | None,
    *,
    has_open_dispute: bool = False,
) -> LineState:
    """Latest decision plus an open dispute, if any. PENDING when no decision exists."""
    if decision is None:
        return LineState.PENDING
    if has_open_dispute and decision.outcome in {
        LineOutcome.APPROVED,
        LineOutcome.PARTIALLY_APPROVED,
        LineOutcome.DENIED,
    }:
        return LineState.UNDER_APPEAL
    return LineState(decision.outcome.value)


def derive_adjudication_state(
    *,
    rejected: bool,
    line_states: Sequence[LineState],
) -> ClaimAdjudicationState:
    """Claim adjudication axis — a current summary of line states."""
    if rejected:
        return ClaimAdjudicationState.REJECTED
    if not line_states or all(state is LineState.PENDING for state in line_states):
        return ClaimAdjudicationState.RECEIVED
    if any(
        state is LineState.NEEDS_REVIEW or state is LineState.UNDER_APPEAL
        for state in line_states
    ):
        return ClaimAdjudicationState.UNDER_REVIEW
    if all(state is LineState.DENIED for state in line_states):
        return ClaimAdjudicationState.DENIED
    if all(state is LineState.APPROVED for state in line_states):
        return ClaimAdjudicationState.APPROVED
    return ClaimAdjudicationState.PARTIALLY_APPROVED


def payable_from_decisions(decisions: Iterable[LineDecision | None]) -> Money:
    """Sum plan_paid from current decisions that have a financial breakdown (D27)."""
    total = 0
    for decision in decisions:
        if decision is not None and decision.amounts is not None:
            total += decision.amounts.plan_paid.minor_units
    return Money(total)


def paid_from_payments(payments: Iterable[Payment]) -> Money:
    return Money(sum(payment.amount.minor_units for payment in payments))


def derive_settlement_state(payable: Money, paid: Money) -> SettlementState:
    """Settlement axis — append-only payments versus current payable."""
    if payable.minor_units == 0:
        return SettlementState.NOTHING_DUE
    if paid < payable:
        return SettlementState.DUE
    if paid == payable:
        return SettlementState.SETTLED
    return SettlementState.OVERPAID


def payment_is_eligible(
    adjudication_state: ClaimAdjudicationState,
    settlement_state: SettlementState,
) -> bool:
    """A payment may be recorded only on an adjudicated claim that is DUE."""
    return (
        adjudication_state
        in (
            ClaimAdjudicationState.APPROVED,
            ClaimAdjudicationState.PARTIALLY_APPROVED,
        )
        and settlement_state is SettlementState.DUE
    )
