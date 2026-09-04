"""Derived line outcomes and the two claim lifecycle axes."""

from __future__ import annotations

from datetime import date, datetime

from app.domain.engine import AdjudicationContext, adjudicate
from app.domain.entities import (
    Claim,
    ClaimLine,
    DecisionAmounts,
    LineDecision,
    Payment,
    Plan,
    Policy,
    ServiceCatalogueEntry,
)
from app.domain.lifecycle import (
    derive_adjudication_state,
    derive_line_state,
    derive_settlement_state,
    line_outcome_from_amounts,
    paid_from_payments,
    payable_from_decisions,
    payment_is_eligible,
)
from app.domain.money import Money
from app.domain.reasons import ReasonCodeId
from app.domain.rules import Benefit
from app.domain.states import (
    ClaimAdjudicationState,
    DecisionSource,
    LineOutcome,
    LineState,
    SettlementState,
)


def _amounts(
    *,
    allowed: int,
    above_allowed: int = 0,
    deductible_applied: int = 0,
    plan_paid: int = 0,
    denied_amount: int = 0,
) -> DecisionAmounts:
    return DecisionAmounts(
        allowed=Money(allowed),
        above_allowed=Money(above_allowed),
        deductible_applied=Money(deductible_applied),
        plan_paid=Money(plan_paid),
        denied_amount=Money(denied_amount),
    )


def _decision(
    line_id: str,
    outcome: LineOutcome,
    *,
    amounts: DecisionAmounts | None = None,
    reason: ReasonCodeId = ReasonCodeId.INFO_COVERED,
) -> LineDecision:
    return LineDecision(
        id=f"dec-{line_id}",
        line_id=line_id,
        sequence=1,
        source=DecisionSource.RULES,
        outcome=outcome,
        reasons=(reason,),
        trace=(),
        plan_version=1,
        decided_at=datetime(2026, 3, 20, 10, 0),
        decided_by="rules",
        amounts=amounts,
    )


def _payment(amount: int, *, payment_id: str = "pay1") -> Payment:
    return Payment(
        id=payment_id,
        claim_id="claim1",
        amount=Money(amount),
        paid_at=datetime(2026, 3, 21, 12, 0),
        reference="ref1",
    )


def _adjudication(*line_states: LineState, rejected: bool = False) -> ClaimAdjudicationState:
    return derive_adjudication_state(rejected=rejected, line_states=line_states)


def test_deductible_only_approval_is_approved_with_plan_paid_zero() -> None:
    amounts = _amounts(allowed=4_000, deductible_applied=4_000)
    assert line_outcome_from_amounts(amounts) is LineOutcome.APPROVED
    assert amounts.plan_paid == Money.zero()


def test_all_approved_claim_is_approved_and_due_when_payable() -> None:
    decisions = (
        _decision("line1", LineOutcome.APPROVED, amounts=_amounts(allowed=4_000, plan_paid=4_000)),
        _decision("line2", LineOutcome.APPROVED, amounts=_amounts(allowed=2_000, plan_paid=2_000)),
    )
    line_states = tuple(derive_line_state(decision) for decision in decisions)
    adjudication = derive_adjudication_state(rejected=False, line_states=line_states)
    payable = payable_from_decisions(decisions)
    settlement = derive_settlement_state(payable, Money.zero())
    assert line_states == (LineState.APPROVED, LineState.APPROVED)
    assert adjudication is ClaimAdjudicationState.APPROVED
    assert payable == Money(6_000)
    assert settlement is SettlementState.DUE
    assert payment_is_eligible(adjudication, settlement) is True


def test_all_denied_claim_is_denied_and_nothing_due() -> None:
    decisions = (
        _decision("line1", LineOutcome.DENIED, reason=ReasonCodeId.DEN_EXCLUDED),
        _decision(
            "line2",
            LineOutcome.DENIED,
            amounts=_amounts(allowed=4_000, denied_amount=4_000),
            reason=ReasonCodeId.DEN_ANNUAL_LIMIT,
        ),
    )
    line_states = tuple(derive_line_state(decision) for decision in decisions)
    adjudication = derive_adjudication_state(rejected=False, line_states=line_states)
    payable = payable_from_decisions(decisions)
    settlement = derive_settlement_state(payable, Money.zero())
    assert adjudication is ClaimAdjudicationState.DENIED
    assert payable == Money.zero()
    assert settlement is SettlementState.NOTHING_DUE
    assert payment_is_eligible(adjudication, settlement) is False


def test_mixed_approved_and_denied_is_partially_approved() -> None:
    decisions = (
        _decision("line1", LineOutcome.APPROVED, amounts=_amounts(allowed=4_000, plan_paid=4_000)),
        _decision("line2", LineOutcome.DENIED, reason=ReasonCodeId.DEN_EXCLUDED),
    )
    line_states = tuple(derive_line_state(decision) for decision in decisions)
    adjudication = derive_adjudication_state(rejected=False, line_states=line_states)
    assert adjudication is ClaimAdjudicationState.PARTIALLY_APPROVED
    assert payable_from_decisions(decisions) == Money(4_000)


def test_any_needs_review_makes_claim_under_review() -> None:
    decisions = (
        _decision("line1", LineOutcome.APPROVED, amounts=_amounts(allowed=4_000, plan_paid=4_000)),
        _decision("line2", LineOutcome.NEEDS_REVIEW, reason=ReasonCodeId.REV_UNKNOWN_SERVICE),
    )
    line_states = tuple(derive_line_state(decision) for decision in decisions)
    adjudication = derive_adjudication_state(rejected=False, line_states=line_states)
    payable = payable_from_decisions(decisions)
    settlement = derive_settlement_state(payable, Money.zero())
    assert LineState.NEEDS_REVIEW in line_states
    assert adjudication is ClaimAdjudicationState.UNDER_REVIEW
    assert payable == Money(4_000)
    assert settlement is SettlementState.DUE
    assert payment_is_eligible(adjudication, settlement) is False


def test_any_under_appeal_makes_claim_under_review() -> None:
    decision = _decision(
        "line1",
        LineOutcome.DENIED,
        reason=ReasonCodeId.DEN_EXCLUDED,
    )
    line_state = derive_line_state(decision, has_open_dispute=True)
    adjudication = derive_adjudication_state(rejected=False, line_states=(line_state,))
    assert line_state is LineState.UNDER_APPEAL
    assert adjudication is ClaimAdjudicationState.UNDER_REVIEW


def test_engine_deductible_only_line_is_approved_with_zero_plan_paid() -> None:
    claim = Claim(
        id="claim1",
        member_id="m1",
        submitted_at=datetime(2026, 3, 20, 9, 0),
        lines=(
            ClaimLine(
                id="line1",
                claim_id="claim1",
                line_number=1,
                provider_id="prov1",
                service_code="PHYSIO-30",
                service_date=date(2026, 3, 15),
                billed_amount=Money(4_000),
                diagnosis_code="M54.5",
            ),
        ),
    )
    ctx = AdjudicationContext(
        policy=Policy(
            id="pol1",
            member_id="m1",
            plan_id="plan1",
            effective_date=date(2026, 1, 1),
            termination_date=None,
        ),
        plan=Plan(
            id="plan1",
            version=3,
            deductible=Money(10_000),
            benefits=(
                Benefit(
                    code="PHYSIO",
                    name="Physiotherapy",
                    covered=True,
                    excluded=False,
                    annual_limit_amount=Money(100_000),
                    annual_visit_limit=12,
                ),
            ),
        ),
        catalogue={
            "PHYSIO-30": ServiceCatalogueEntry(
                service_code="PHYSIO-30",
                description="Physio",
                benefit_code="PHYSIO",
                scheduled_amount=Money(4_000),
            )
        },
        suspected_duplicate_keys=frozenset(),
        as_of=date(2026, 3, 20),
        decided_at=datetime(2026, 3, 20, 10, 0),
    )
    result = adjudicate(claim, ctx)
    decision = result.line_results[0].decision
    assert decision is not None
    assert decision.outcome is LineOutcome.APPROVED
    assert decision.amounts is not None
    assert decision.amounts.plan_paid == Money.zero()
    assert decision.amounts.deductible_applied == Money(4_000)
    assert line_outcome_from_amounts(decision.amounts) is LineOutcome.APPROVED
    line_states = (derive_line_state(decision),)
    adjudication = derive_adjudication_state(rejected=False, line_states=line_states)
    payable = payable_from_decisions((decision,))
    settlement = derive_settlement_state(payable, Money.zero())
    assert adjudication is ClaimAdjudicationState.APPROVED
    assert payable == Money.zero()
    assert settlement is SettlementState.NOTHING_DUE
    assert payment_is_eligible(adjudication, settlement) is False


def test_payable_zero_is_nothing_due() -> None:
    payable = Money.zero()
    assert derive_settlement_state(payable, Money.zero()) is SettlementState.NOTHING_DUE
    assert payment_is_eligible(ClaimAdjudicationState.APPROVED, SettlementState.NOTHING_DUE) is False


def test_paid_less_than_payable_is_due() -> None:
    payable = Money(4_000)
    paid = Money(1_000)
    assert derive_settlement_state(payable, paid) is SettlementState.DUE
    assert payment_is_eligible(ClaimAdjudicationState.APPROVED, SettlementState.DUE) is True


def test_paid_equal_to_payable_is_settled() -> None:
    decisions = (
        _decision("line1", LineOutcome.APPROVED, amounts=_amounts(allowed=4_000, plan_paid=4_000)),
    )
    payable = payable_from_decisions(decisions)
    paid = paid_from_payments((_payment(4_000),))
    settlement = derive_settlement_state(payable, paid)
    assert payable == paid == Money(4_000)
    assert settlement is SettlementState.SETTLED
    assert payment_is_eligible(ClaimAdjudicationState.APPROVED, settlement) is False


def test_paid_greater_than_payable_is_overpaid() -> None:
    settlement = derive_settlement_state(Money(2_000), Money(4_000))
    assert settlement is SettlementState.OVERPAID
    assert payment_is_eligible(ClaimAdjudicationState.APPROVED, settlement) is False


def test_dispute_reopens_adjudication_while_settlement_stays_settled() -> None:
    approved = _decision(
        "line1",
        LineOutcome.APPROVED,
        amounts=_amounts(allowed=4_000, plan_paid=4_000),
    )
    denied = _decision("line2", LineOutcome.DENIED, reason=ReasonCodeId.DEN_EXCLUDED)
    decisions = (approved, denied)
    payable = payable_from_decisions(decisions)
    paid = paid_from_payments((_payment(4_000),))
    before_states = tuple(derive_line_state(decision) for decision in decisions)
    before = derive_adjudication_state(rejected=False, line_states=before_states)
    settled = derive_settlement_state(payable, paid)
    assert before is ClaimAdjudicationState.PARTIALLY_APPROVED
    assert settled is SettlementState.SETTLED

    after_states = (
        derive_line_state(approved),
        derive_line_state(denied, has_open_dispute=True),
    )
    after = derive_adjudication_state(rejected=False, line_states=after_states)
    still_settled = derive_settlement_state(payable, paid)
    assert after_states[1] is LineState.UNDER_APPEAL
    assert after is ClaimAdjudicationState.UNDER_REVIEW
    assert still_settled is SettlementState.SETTLED
    assert payment_is_eligible(after, still_settled) is False


def test_unadjudicated_claim_is_received() -> None:
    assert _adjudication() is ClaimAdjudicationState.RECEIVED
    assert _adjudication(LineState.PENDING) is ClaimAdjudicationState.RECEIVED


def test_rejected_claim_is_rejected() -> None:
    assert _adjudication(rejected=True) is ClaimAdjudicationState.REJECTED


def test_needs_review_is_not_under_appeal_even_if_dispute_flag_set() -> None:
    decision = _decision(
        "line1",
        LineOutcome.NEEDS_REVIEW,
        reason=ReasonCodeId.REV_UNKNOWN_SERVICE,
    )
    assert derive_line_state(decision, has_open_dispute=True) is LineState.NEEDS_REVIEW
