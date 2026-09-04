from app.domain.accumulators import AccumulatorScope
from app.domain.states import (
    ClaimAdjudicationState,
    DecisionSource,
    DisputeState,
    LineOutcome,
    LineState,
    ReviewResolutionMode,
    SettlementState,
)


def test_line_outcome_values_match_design() -> None:
    assert set(LineOutcome) == {
        LineOutcome.APPROVED,
        LineOutcome.PARTIALLY_APPROVED,
        LineOutcome.DENIED,
        LineOutcome.NEEDS_REVIEW,
    }


def test_line_state_includes_pending_and_under_appeal() -> None:
    assert LineState.PENDING == "PENDING"
    assert LineState.UNDER_APPEAL == "UNDER_APPEAL"


def test_claim_adjudication_state_values_match_design() -> None:
    assert ClaimAdjudicationState.RECEIVED == "RECEIVED"
    assert ClaimAdjudicationState.REJECTED == "REJECTED"
    assert ClaimAdjudicationState.UNDER_REVIEW == "UNDER_REVIEW"


def test_settlement_state_values_match_design() -> None:
    assert set(SettlementState) == {
        SettlementState.NOTHING_DUE,
        SettlementState.DUE,
        SettlementState.SETTLED,
        SettlementState.OVERPAID,
    }


def test_accumulator_scope_values_match_design() -> None:
    assert set(AccumulatorScope) == {
        AccumulatorScope.DEDUCTIBLE,
        AccumulatorScope.BENEFIT_AMOUNT,
        AccumulatorScope.BENEFIT_VISITS,
    }


def test_decision_source_is_rules_only_in_this_implementation() -> None:
    assert DecisionSource.RULES == "RULES"
    assert list(DecisionSource) == [DecisionSource.RULES]


def test_dispute_and_review_resolution_modes() -> None:
    assert DisputeState.OPEN == "OPEN"
    assert DisputeState.CLOSED == "CLOSED"
    assert ReviewResolutionMode.CORRECT_FACTS == "CORRECT_FACTS"
    assert ReviewResolutionMode.UPHOLD == "UPHOLD"
