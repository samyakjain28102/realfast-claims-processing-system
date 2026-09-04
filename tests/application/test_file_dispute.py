"""Application tests for filing disputes and resolving appeals."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.application.claim_queries import get_claim
from app.application.file_dispute import (
    DisputeAlreadyOpenError,
    DisputeNotAppealableError,
    file_dispute,
)
from app.application.resolve_review import resolve_review
from app.application.submit_claim import submit_claim
from app.domain.accumulators import AccumulatorKey, AccumulatorScope
from app.domain.entities import (
    Claim,
    ClaimLine,
    LineFactCorrections,
    Member,
    Payment,
    Plan,
    Policy,
    Provider,
    ServiceCatalogueEntry,
)
from app.domain.money import Money
from app.domain.reasons import ReasonCodeId
from app.domain.rules import Benefit
from app.domain.states import (
    ClaimAdjudicationState,
    DisputeState,
    LineOutcome,
    ReviewResolutionMode,
    SettlementState,
)
from app.infrastructure.db import SqliteDatabase, open_database


@pytest.fixture
def db() -> SqliteDatabase:
    database = open_database()
    yield database
    database.close()


def _physio(*, limit: int = 10_000, visits: int = 12) -> Benefit:
    return Benefit(
        code="PHYSIO",
        name="Physiotherapy",
        covered=True,
        excluded=False,
        annual_limit_amount=Money(limit),
        annual_visit_limit=visits,
    )


def _cosmetic() -> Benefit:
    return Benefit(
        code="COSMETIC",
        name="Cosmetic procedures",
        covered=True,
        excluded=True,
        annual_limit_amount=None,
        annual_visit_limit=None,
    )


def _seed(
    db: SqliteDatabase,
    *,
    deductible: int = 0,
    limit: int = 10_000,
    visits: int = 12,
    plan_version: int = 1,
) -> None:
    db.members.add(Member(id="m1", name="Ada", date_of_birth=date(1990, 1, 1)))
    db.providers.add(Provider(id="prov1", name="City Clinic"))
    db.plans.add(
        Plan(
            id="plan1",
            version=plan_version,
            deductible=Money(deductible),
            benefits=(_physio(limit=limit, visits=visits), _cosmetic()),
        )
    )
    db.policies.add(
        Policy(
            id="pol1",
            member_id="m1",
            plan_id="plan1",
            effective_date=date(2026, 1, 1),
            termination_date=None,
        )
    )
    db.catalogue.add(
        ServiceCatalogueEntry(
            service_code="PHYSIO-30",
            description="Physio session",
            benefit_code="PHYSIO",
            scheduled_amount=Money(4_000),
        )
    )
    db.catalogue.add(
        ServiceCatalogueEntry(
            service_code="COSMETIC-1",
            description="Cosmetic procedure",
            benefit_code="COSMETIC",
            scheduled_amount=Money(10_000),
        )
    )


def _line(
    claim_id: str,
    number: int,
    *,
    service_code: str,
    service_date: date = date(2026, 3, 15),
    billed: int = 5_000,
) -> ClaimLine:
    return ClaimLine(
        id=f"{claim_id}-L{number}",
        claim_id=claim_id,
        line_number=number,
        provider_id="prov1",
        service_code=service_code,
        service_date=service_date,
        billed_amount=Money(billed),
        diagnosis_code="M54.5",
    )


def _claim(claim_id: str, *lines: ClaimLine) -> Claim:
    return Claim(
        id=claim_id,
        member_id="m1",
        submitted_at=datetime(2026, 3, 20, 10, 0),
        lines=lines,
    )


def _pay(db: SqliteDatabase, claim_id: str, amount: int) -> None:
    db.payments.add(
        Payment(
            id=f"{claim_id}:pay1",
            claim_id=claim_id,
            amount=Money(amount),
            paid_at=datetime(2026, 3, 22, 12, 0),
            reference="chk-1",
        )
    )


def _dispute(db: SqliteDatabase, claim_id: str, line_number: int):
    return file_dispute(
        db,
        claim_id=claim_id,
        line_number=line_number,
        member_reason="please reconsider",
    )


def _correct(db: SqliteDatabase, line_id: str, corrections: LineFactCorrections):
    return resolve_review(
        db,
        line_id=line_id,
        mode=ReviewResolutionMode.CORRECT_FACTS,
        reviewer_id="rev1",
        note="correct facts",
        corrections=corrections,
        decided_at=datetime(2026, 3, 23, 9, 0),
    )


def _uphold(db: SqliteDatabase, line_id: str):
    return resolve_review(
        db,
        line_id=line_id,
        mode=ReviewResolutionMode.UPHOLD,
        reviewer_id="rev1",
        note="original decision stands",
        decided_at=datetime(2026, 3, 23, 9, 0),
    )


def _amount_key(year: int = 2026) -> AccumulatorKey:
    return AccumulatorKey(
        member_id="m1",
        plan_year=year,
        scope=AccumulatorScope.BENEFIT_AMOUNT,
        benefit_code="PHYSIO",
    )


def _visit_key(year: int = 2026) -> AccumulatorKey:
    return AccumulatorKey(
        member_id="m1",
        plan_year=year,
        scope=AccumulatorScope.BENEFIT_VISITS,
        benefit_code="PHYSIO",
    )


def test_denied_line_successfully_appealed(db: SqliteDatabase) -> None:
    _seed(db)
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="COSMETIC-1", billed=10_000)),
    )
    original = db.decisions.current_for_line("c1-L1")
    assert original is not None
    assert original.outcome is LineOutcome.DENIED
    assert ReasonCodeId.DEN_EXCLUDED in original.reasons
    assert db.accumulators.balance(_amount_key()) == 0

    filed = _dispute(db, "c1", 1)
    view = get_claim(db, "c1")
    assert view.lines[0].line_state == "UNDER_APPEAL"
    assert view.adjudication_state == ClaimAdjudicationState.UNDER_REVIEW.value
    assert db.decisions.get(original.id) == original
    assert filed.disputed_decision_id == original.id

    result = _correct(db, "c1-L1", LineFactCorrections(service_code="PHYSIO-30"))
    current = db.decisions.current_for_line("c1-L1")
    assert result.adjudication_state is ClaimAdjudicationState.APPROVED
    assert current is not None
    assert current.id != original.id
    assert current.sequence == 2
    assert current.source.value == "RULES"
    assert current.outcome is LineOutcome.APPROVED
    assert current.plan_version == 1
    assert current.amounts is not None
    assert current.amounts.plan_paid == Money(4_000)
    assert db.decisions.get(original.id) == original
    assert db.accumulators.balance(_amount_key()) == 4_000
    assert db.disputes.get(filed.dispute.id) is not None
    assert db.disputes.get(filed.dispute.id).state is DisputeState.CLOSED
    resolution = db.reviews.list_for_line("c1-L1")[0]
    assert resolution.mode is ReviewResolutionMode.CORRECT_FACTS
    assert resolution.dispute_id == filed.dispute.id


def test_denied_line_upheld(db: SqliteDatabase) -> None:
    _seed(db)
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="COSMETIC-1", billed=10_000)),
    )
    original = db.decisions.current_for_line("c1-L1")
    assert original is not None
    db.plans.add(
        Plan(
            id="plan1",
            version=2,
            deductible=Money.zero(),
            benefits=(
                _physio(),
                Benefit(
                    code="COSMETIC",
                    name="Cosmetic procedures",
                    covered=True,
                    excluded=False,
                    annual_limit_amount=None,
                    annual_visit_limit=None,
                ),
            ),
        )
    )
    filed = _dispute(db, "c1", 1)
    result = _uphold(db, "c1-L1")
    current = db.decisions.current_for_line("c1-L1")
    assert result.adjudication_state is ClaimAdjudicationState.DENIED
    assert current is not None
    assert current.sequence == 2
    assert current.outcome is LineOutcome.DENIED
    assert ReasonCodeId.DEN_EXCLUDED in current.reasons
    assert current.source.value == "RULES"
    assert current.plan_version == 1
    assert db.decisions.get(original.id) == original
    assert db.accumulators.balance(_amount_key()) == 0
    assert db.accumulators.list_for_decision(current.id) == ()
    assert db.disputes.get(filed.dispute.id).state is DisputeState.CLOSED
    resolution = db.reviews.list_for_line("c1-L1")[0]
    assert resolution.mode is ReviewResolutionMode.UPHOLD
    assert resolution.corrections is None


def test_approved_line_with_non_appealable_deductible_reason(
    db: SqliteDatabase,
) -> None:
    _seed(db, deductible=10_000)
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="PHYSIO-30", billed=4_000)),
    )
    decision = db.decisions.current_for_line("c1-L1")
    assert decision is not None
    assert decision.outcome is LineOutcome.APPROVED
    assert ReasonCodeId.MEM_DEDUCTIBLE in decision.reasons
    assert ReasonCodeId.DEN_EXCLUDED not in decision.reasons
    with pytest.raises(DisputeNotAppealableError):
        _dispute(db, "c1", 1)
    assert db.disputes.list_for_line("c1-L1") == ()
    assert get_claim(db, "c1").adjudication_state == ClaimAdjudicationState.APPROVED.value
    assert get_claim(db, "c1").lines[0].line_state == "APPROVED"


def test_post_payment_appeal_increases_payable(db: SqliteDatabase) -> None:
    _seed(db)
    submit_claim(
        db,
        _claim(
            "c1",
            _line("c1", 1, service_code="PHYSIO-30", service_date=date(2026, 3, 15)),
            _line(
                "c1",
                2,
                service_code="COSMETIC-1",
                service_date=date(2026, 3, 16),
                billed=10_000,
            ),
        ),
    )
    before = get_claim(db, "c1")
    assert before.payable_minor == 4_000
    _pay(db, "c1", 4_000)
    settled = get_claim(db, "c1")
    assert settled.settlement_state == SettlementState.SETTLED.value
    assert settled.adjudication_state == ClaimAdjudicationState.PARTIALLY_APPROVED.value

    _dispute(db, "c1", 2)
    under_review = get_claim(db, "c1")
    assert under_review.adjudication_state == ClaimAdjudicationState.UNDER_REVIEW.value
    assert under_review.settlement_state == SettlementState.SETTLED.value
    assert under_review.payable_minor == 4_000

    _correct(db, "c1-L2", LineFactCorrections(service_code="PHYSIO-30"))
    after = get_claim(db, "c1")
    assert after.payable_minor == 8_000
    assert after.settlement_state == SettlementState.DUE.value
    assert after.adjudication_state == ClaimAdjudicationState.APPROVED.value
    assert after.lines[1].decision is not None
    assert after.lines[1].decision.outcome == LineOutcome.APPROVED.value


def test_post_payment_appeal_decreases_payable(db: SqliteDatabase) -> None:
    _seed(db, limit=6_000)
    submit_claim(
        db,
        _claim(
            "c1",
            _line("c1", 1, service_code="PHYSIO-30", service_date=date(2026, 3, 15)),
            _line("c1", 2, service_code="PHYSIO-30", service_date=date(2026, 3, 16)),
        ),
    )
    before = get_claim(db, "c1")
    assert before.payable_minor == 6_000
    assert before.lines[1].decision is not None
    assert before.lines[1].decision.outcome == LineOutcome.PARTIALLY_APPROVED.value
    _pay(db, "c1", 6_000)
    assert get_claim(db, "c1").settlement_state == SettlementState.SETTLED.value

    _dispute(db, "c1", 2)
    _correct(db, "c1-L2", LineFactCorrections(service_code="COSMETIC-1"))
    after = get_claim(db, "c1")
    assert after.payable_minor == 4_000
    assert after.lines[1].decision is not None
    assert after.lines[1].decision.outcome == LineOutcome.DENIED.value
    assert ReasonCodeId.DEN_EXCLUDED.value in {
        reason.code for reason in after.lines[1].decision.reasons
    }


def test_overpaid_settlement_state_after_appeal_reduces_payable(
    db: SqliteDatabase,
) -> None:
    _seed(db, limit=6_000)
    submit_claim(
        db,
        _claim(
            "c1",
            _line("c1", 1, service_code="PHYSIO-30", service_date=date(2026, 3, 15)),
            _line("c1", 2, service_code="PHYSIO-30", service_date=date(2026, 3, 16)),
        ),
    )
    _pay(db, "c1", 6_000)
    _dispute(db, "c1", 2)
    _correct(db, "c1-L2", LineFactCorrections(service_code="COSMETIC-1"))
    after = get_claim(db, "c1")
    assert after.payable_minor == 4_000
    assert after.settlement_state == SettlementState.OVERPAID.value
    assert len(db.payments.list_for_claim("c1")) == 1
    assert db.payments.list_for_claim("c1")[0].amount == Money(6_000)


def test_appeal_consuming_the_final_benefit_amount(db: SqliteDatabase) -> None:
    _seed(db, limit=10_000)
    submit_claim(
        db,
        _claim(
            "prior",
            _line("prior", 1, service_code="PHYSIO-30", service_date=date(2026, 3, 1)),
            _line("prior", 2, service_code="PHYSIO-30", service_date=date(2026, 3, 2)),
        ),
    )
    assert db.accumulators.balance(_amount_key()) == 8_000
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="COSMETIC-1", billed=10_000)),
    )
    _dispute(db, "c1", 1)
    result = _correct(db, "c1-L1", LineFactCorrections(service_code="PHYSIO-30"))
    current = db.decisions.current_for_line("c1-L1")
    assert current is not None
    assert current.outcome is LineOutcome.PARTIALLY_APPROVED
    assert current.amounts is not None
    assert current.amounts.plan_paid == Money(2_000)
    assert ReasonCodeId.DEN_ANNUAL_LIMIT in current.reasons
    assert result.payable == Money(2_000)
    assert db.accumulators.balance(_amount_key()) == 10_000


def test_appeal_causing_a_visit_limit_interaction(db: SqliteDatabase) -> None:
    _seed(db, visits=1)
    submit_claim(
        db,
        _claim(
            "c1",
            _line("c1", 1, service_code="PHYSIO-30", service_date=date(2026, 3, 15)),
            _line(
                "c1",
                2,
                service_code="COSMETIC-1",
                service_date=date(2026, 3, 16),
                billed=10_000,
            ),
        ),
    )
    assert db.accumulators.balance(_visit_key()) == 1
    sibling_first = db.decisions.current_for_line("c1-L1")
    assert sibling_first is not None
    _dispute(db, "c1", 2)
    _correct(db, "c1-L2", LineFactCorrections(service_code="PHYSIO-30"))
    appealed = db.decisions.current_for_line("c1-L2")
    sibling = db.decisions.current_for_line("c1-L1")
    assert appealed is not None
    assert sibling is not None
    assert appealed.outcome is LineOutcome.DENIED
    assert ReasonCodeId.DEN_VISIT_LIMIT in appealed.reasons
    assert sibling.outcome is LineOutcome.APPROVED
    assert sibling.sequence == 2
    assert db.decisions.get(sibling_first.id) == sibling_first
    assert db.accumulators.balance(_visit_key()) == 1
    assert db.accumulators.balance(_amount_key()) == 4_000
    assert not any(
        entry.reverses_entry_id is None
        and not db.accumulators.is_reversed(entry.id)
        for entry in db.accumulators.list_for_decision(appealed.id)
    )


def test_second_open_dispute_on_same_line_is_rejected(db: SqliteDatabase) -> None:
    _seed(db)
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="COSMETIC-1", billed=10_000)),
    )
    _dispute(db, "c1", 1)
    with pytest.raises(DisputeAlreadyOpenError):
        _dispute(db, "c1", 1)
    assert len(db.disputes.list_open_for_line("c1-L1")) == 1


def test_uphold_re_adjudication_preserves_monetary_outcome(db: SqliteDatabase) -> None:
    _seed(db)
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="COSMETIC-1", billed=10_000)),
    )
    before = get_claim(db, "c1")
    original = db.decisions.current_for_line("c1-L1")
    assert original is not None
    assert original.amounts is None

    _dispute(db, "c1", 1)
    result = _uphold(db, "c1-L1")
    after = get_claim(db, "c1")

    assert result.payable == Money.zero()
    assert after.payable_minor == before.payable_minor
    current = db.decisions.current_for_line("c1-L1")
    assert current is not None
    assert current.sequence == 2
    assert current.outcome is LineOutcome.DENIED
    assert current.amounts is None
    assert db.accumulators.balance(_amount_key()) == 0


def test_appeal_on_sibling_reverses_deductible_ledger_without_changing_plan_paid(
    db: SqliteDatabase,
) -> None:
    _seed(db, deductible=10_000)
    submit_claim(
        db,
        _claim(
            "c1",
            _line("c1", 1, service_code="PHYSIO-30", service_date=date(2026, 3, 15)),
            _line(
                "c1",
                2,
                service_code="COSMETIC-1",
                service_date=date(2026, 3, 16),
                billed=10_000,
            ),
        ),
    )
    line1_first = db.decisions.current_for_line("c1-L1")
    assert line1_first is not None
    assert line1_first.amounts is not None
    assert line1_first.amounts.plan_paid == Money.zero()
    assert line1_first.amounts.deductible_applied == Money(4_000)
    first_deductible_entries = [
        entry
        for entry in db.accumulators.list_for_decision(line1_first.id)
        if entry.key.scope is AccumulatorScope.DEDUCTIBLE
    ]
    assert len(first_deductible_entries) == 1

    _dispute(db, "c1", 2)
    _correct(db, "c1-L2", LineFactCorrections(service_code="PHYSIO-30"))

    line1_second = db.decisions.current_for_line("c1-L1")
    assert line1_second is not None
    assert line1_second.id != line1_first.id
    assert line1_second.amounts is not None
    assert line1_second.amounts.plan_paid == Money.zero()
    assert line1_second.amounts.deductible_applied == Money(4_000)

    reversed_ids = {
        entry.reverses_entry_id
        for entry in db.accumulators.list_for_decision(line1_second.id)
        if entry.reverses_entry_id is not None
    }
    assert first_deductible_entries[0].id in reversed_ids
