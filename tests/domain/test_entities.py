from datetime import date, datetime

import pytest

from app.domain.accumulators import AccumulatorKey, AccumulatorScope
from app.domain.entities import (
    Claim,
    ClaimLine,
    DecisionAmounts,
    Dispute,
    LineDecision,
    LineFactCorrections,
    Member,
    Payment,
    Plan,
    Policy,
    Provider,
    ReviewResolution,
    ServiceCatalogueEntry,
    TraceStep,
)
from app.domain.money import Money
from app.domain.reasons import ReasonCodeId
from app.domain.rules import Benefit
from app.domain.states import (
    DecisionSource,
    DisputeState,
    LineOutcome,
    ReviewResolutionMode,
)


def _line(**overrides: object) -> ClaimLine:
    defaults = {
        "id": "line1",
        "claim_id": "claim1",
        "line_number": 1,
        "provider_id": "prov1",
        "service_code": "PHYSIO-30",
        "service_date": date(2026, 3, 15),
        "billed_amount": Money(5_000),
        "diagnosis_code": "M54.5",
    }
    defaults.update(overrides)
    return ClaimLine(**defaults)  # type: ignore[arg-type]


def test_member_has_identity_only() -> None:
    member = Member(id="m1", name="Ada Lovelace", date_of_birth=date(1990, 1, 1))
    assert not hasattr(member, "diagnosis_code")


def test_claim_line_carries_clinical_data_and_service_date() -> None:
    line = _line()
    assert line.diagnosis_code == "M54.5"
    assert line.service_date == date(2026, 3, 15)


def test_claim_has_no_stored_adjudication_or_settlement_state() -> None:
    claim = Claim(
        id="claim1",
        member_id="m1",
        submitted_at=datetime(2026, 3, 20, 10, 0),
        lines=(_line(),),
    )
    assert not hasattr(claim, "adjudication_state")
    assert not hasattr(claim, "settlement_state")


def test_claim_rejects_duplicate_line_numbers() -> None:
    with pytest.raises(ValueError, match="line_number"):
        Claim(
            id="claim1",
            member_id="m1",
            submitted_at=datetime(2026, 3, 20, 10, 0),
            lines=(
                _line(id="line1", line_number=1),
                _line(id="line2", line_number=1),
            ),
        )


def test_policy_has_no_deductible_plan_does() -> None:
    policy = Policy(
        id="pol1",
        member_id="m1",
        plan_id="plan1",
        effective_date=date(2026, 1, 1),
        termination_date=None,
    )
    plan = Plan(
        id="plan1",
        version=1,
        deductible=Money(50_000),
        benefits=(),
    )
    assert not hasattr(policy, "deductible")
    assert plan.deductible == Money(50_000)


def test_plan_benefits_and_service_catalogue_use_money() -> None:
    benefit = Benefit(
        code="PHYSIO",
        name="Physiotherapy",
        covered=True,
        excluded=False,
        annual_limit_amount=Money(100_000),
        annual_visit_limit=12,
    )
    plan = Plan(id="plan1", version=2, deductible=Money(10_000), benefits=(benefit,))
    entry = ServiceCatalogueEntry(
        service_code="PHYSIO-30",
        description="Physio session",
        benefit_code="PHYSIO",
        scheduled_amount=Money(4_000),
    )
    assert plan.version == 2
    assert entry.scheduled_amount == Money(4_000)


def test_pre_pricing_decision_has_no_amount_breakdown() -> None:
    decision = LineDecision(
        id="dec1",
        line_id="line1",
        sequence=1,
        source=DecisionSource.RULES,
        outcome=LineOutcome.NEEDS_REVIEW,
        reasons=(ReasonCodeId.REV_UNKNOWN_SERVICE,),
        trace=(),
        plan_version=1,
        decided_at=datetime(2026, 3, 20, 10, 1),
        decided_by="rules",
        amounts=None,
    )
    assert decision.amounts is None


def test_priced_decision_amounts_obey_conservation() -> None:
    amounts = DecisionAmounts(
        allowed=Money(4_000),
        above_allowed=Money(1_000),
        deductible_applied=Money(4_000),
        plan_paid=Money(0),
        denied_amount=Money(0),
    )
    amounts.check_conservation(Money(5_000))


def test_priced_decision_amounts_reject_conservation_violation() -> None:
    amounts = DecisionAmounts(
        allowed=Money(4_000),
        above_allowed=Money(0),
        deductible_applied=Money(4_000),
        plan_paid=Money(0),
        denied_amount=Money(0),
    )
    with pytest.raises(ValueError, match="conservation"):
        amounts.check_conservation(Money(5_000))


def test_line_decision_is_append_only_shape() -> None:
    decision = LineDecision(
        id="dec2",
        line_id="line1",
        sequence=2,
        source=DecisionSource.RULES,
        outcome=LineOutcome.DENIED,
        reasons=(ReasonCodeId.DEN_EXCLUDED,),
        trace=(
            TraceStep(
                step="exclusion",
                rule="BENEFIT.COSMETIC.excluded",
                plan_version=1,
                inputs={},
                result="denied",
            ),
        ),
        plan_version=1,
        decided_at=datetime(2026, 3, 21, 9, 0),
        decided_by="rules",
    )
    assert decision.sequence == 2


def test_payment_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        Payment(
            id="pay1",
            claim_id="claim1",
            amount=Money(0),
            paid_at=datetime(2026, 3, 22, 12, 0),
            reference="ref1",
        )


def test_dispute_targets_a_specific_decision() -> None:
    dispute = Dispute(
        id="disp1",
        line_id="line1",
        disputed_decision_id="dec1",
        member_reason="I believe this should be covered",
        state=DisputeState.OPEN,
    )
    assert dispute.disputed_decision_id == "dec1"


def test_review_resolution_correct_facts_requires_corrections() -> None:
    resolution = ReviewResolution(
        id="res1",
        line_id="line1",
        mode=ReviewResolutionMode.CORRECT_FACTS,
        reviewer_id="rev1",
        note="Corrected service code",
        resulting_decision_id="dec3",
        corrections=LineFactCorrections(service_code="PHYSIO-60"),
    )
    assert resolution.corrections is not None
    assert resolution.corrections.service_code == "PHYSIO-60"


def test_review_resolution_uphold_rejects_corrections() -> None:
    with pytest.raises(ValueError, match="uphold"):
        ReviewResolution(
            id="res2",
            line_id="line1",
            mode=ReviewResolutionMode.UPHOLD,
            reviewer_id="rev1",
            note="Denial stands",
            resulting_decision_id="dec4",
            dispute_id="disp1",
            corrections=LineFactCorrections(service_code="PHYSIO-60"),
        )


def test_provider_is_thin_record() -> None:
    provider = Provider(id="prov1", name="City Clinic")
    assert provider.name == "City Clinic"


def test_accumulator_key_on_member_scope() -> None:
    key = AccumulatorKey(
        member_id="m1",
        plan_year=2026,
        scope=AccumulatorScope.DEDUCTIBLE,
        benefit_code=None,
    )
    assert key.member_id == "m1"
