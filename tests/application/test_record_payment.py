"""Application tests for recording payments and assembling the EOB."""

from __future__ import annotations

from datetime import date, datetime

import pytest
import sqlite3

from app.application.build_eob import build_eob
from app.application.claim_queries import get_claim
from app.application.file_dispute import file_dispute
from app.application.record_payment import (
    PaymentAmountMismatchError,
    PaymentNotAllowedError,
    PaymentWhileUnderReviewError,
    record_payment,
)
from app.application.resolve_review import resolve_review
from app.application.submit_claim import submit_claim
from app.domain.entities import (
    Claim,
    ClaimLine,
    LineFactCorrections,
    Member,
    Plan,
    Policy,
    Provider,
    ServiceCatalogueEntry,
)
from app.domain.money import Money
from app.domain.reasons import ReasonCodeId, get_reason
from app.domain.rules import Benefit
from app.domain.states import (
    ClaimAdjudicationState,
    ReviewResolutionMode,
    SettlementState,
)
from app.infrastructure.db import SqliteDatabase, open_database


@pytest.fixture
def db() -> SqliteDatabase:
    database = open_database()
    yield database
    database.close()


def _physio(*, limit: int = 10_000) -> Benefit:
    return Benefit(
        code="PHYSIO",
        name="Physiotherapy",
        covered=True,
        excluded=False,
        annual_limit_amount=Money(limit),
        annual_visit_limit=12,
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


def _seed(db: SqliteDatabase, *, deductible: int = 0, limit: int = 10_000) -> None:
    db.members.add(Member(id="m1", name="Ada", date_of_birth=date(1990, 1, 1)))
    db.providers.add(Provider(id="prov1", name="City Clinic"))
    db.plans.add(
        Plan(
            id="plan1",
            version=1,
            deductible=Money(deductible),
            benefits=(_physio(limit=limit), _cosmetic()),
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


def _pay(db: SqliteDatabase, claim_id: str, amount: int, *, reference: str = "chk-1"):
    return record_payment(
        db,
        claim_id=claim_id,
        amount=Money(amount),
        reference=reference,
        paid_at=datetime(2026, 3, 22, 12, 0),
    )


def test_exact_payment_settles_an_approved_claim(db: SqliteDatabase) -> None:
    _seed(db)
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="PHYSIO-30")),
    )
    view = get_claim(db, "c1")
    assert view.adjudication_state == ClaimAdjudicationState.APPROVED.value
    assert view.settlement_state == SettlementState.DUE.value
    assert view.payable_minor == 4_000

    with pytest.raises(PaymentAmountMismatchError):
        _pay(db, "c1", 3_999)
    with pytest.raises(PaymentAmountMismatchError):
        _pay(db, "c1", 4_001)
    assert db.payments.list_for_claim("c1") == ()

    result = _pay(db, "c1", 4_000)
    assert result.settlement_state is SettlementState.SETTLED
    assert result.adjudication_state is ClaimAdjudicationState.APPROVED
    assert result.payable == Money(4_000)
    assert result.paid == Money(4_000)
    stored = db.payments.list_for_claim("c1")
    assert len(stored) == 1
    assert stored[0].amount == Money(4_000)
    assert get_claim(db, "c1").settlement_state == SettlementState.SETTLED.value

    with pytest.raises(sqlite3.Error, match="append-only"):
        db.connection.execute(
            "UPDATE payments SET amount_minor = 1 WHERE id = ?",
            (stored[0].id,),
        )


def test_payment_after_approval(db: SqliteDatabase) -> None:
    _seed(db)
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="PHYSIO-30")),
    )
    before = db.decisions.current_for_line("c1-L1")
    result = _pay(db, "c1", 4_000)
    after = db.decisions.current_for_line("c1-L1")
    assert result.settlement_state is SettlementState.SETTLED
    assert before is not None and after == before


def test_payment_while_under_review_is_rejected(db: SqliteDatabase) -> None:
    _seed(db)
    submit_claim(
        db,
        _claim(
            "c1",
            _line("c1", 1, service_code="PHYSIO-30"),
            _line("c1", 2, service_code="NOT-IN-CATALOG", billed=1_000),
        ),
    )
    view = get_claim(db, "c1")
    assert view.adjudication_state == ClaimAdjudicationState.UNDER_REVIEW.value
    assert view.payable_minor == 4_000
    with pytest.raises(PaymentWhileUnderReviewError):
        _pay(db, "c1", 4_000)
    assert db.payments.list_for_claim("c1") == ()
    assert get_claim(db, "c1").settlement_state == SettlementState.DUE.value


def test_zero_payable_cannot_be_paid(db: SqliteDatabase) -> None:
    _seed(db, deductible=10_000)
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="PHYSIO-30", billed=4_000)),
    )
    view = get_claim(db, "c1")
    assert view.adjudication_state == ClaimAdjudicationState.APPROVED.value
    assert view.payable_minor == 0
    assert view.settlement_state == SettlementState.NOTHING_DUE.value
    with pytest.raises(PaymentNotAllowedError):
        _pay(db, "c1", 1)
    assert db.payments.list_for_claim("c1") == ()


def test_supplementary_payment_after_successful_post_payment_appeal(
    db: SqliteDatabase,
) -> None:
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
    first = _pay(db, "c1", 4_000)
    assert first.settlement_state is SettlementState.SETTLED

    file_dispute(db, claim_id="c1", line_number=2, member_reason="should be physio")
    resolve_review(
        db,
        line_id="c1-L2",
        mode=ReviewResolutionMode.CORRECT_FACTS,
        reviewer_id="rev1",
        note="mapped to physio",
        corrections=LineFactCorrections(service_code="PHYSIO-30"),
        decided_at=datetime(2026, 3, 23, 9, 0),
    )
    due = get_claim(db, "c1")
    assert due.payable_minor == 8_000
    assert due.settlement_state == SettlementState.DUE.value

    with pytest.raises(PaymentAmountMismatchError):
        _pay(db, "c1", 8_000, reference="chk-2")
    second = _pay(db, "c1", 4_000, reference="chk-2")
    assert second.settlement_state is SettlementState.SETTLED
    assert second.paid == Money(8_000)
    assert len(db.payments.list_for_claim("c1")) == 2


def test_overpaid_state_after_appeal_reduces_payable(db: SqliteDatabase) -> None:
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
    assert get_claim(db, "c1").settlement_state == SettlementState.SETTLED.value

    file_dispute(db, claim_id="c1", line_number=2, member_reason="not covered")
    resolve_review(
        db,
        line_id="c1-L2",
        mode=ReviewResolutionMode.CORRECT_FACTS,
        reviewer_id="rev1",
        note="cosmetic",
        corrections=LineFactCorrections(service_code="COSMETIC-1"),
        decided_at=datetime(2026, 3, 23, 9, 0),
    )
    after = get_claim(db, "c1")
    assert after.payable_minor == 4_000
    assert after.settlement_state == SettlementState.OVERPAID.value
    with pytest.raises(PaymentNotAllowedError):
        _pay(db, "c1", 4_000, reference="clawback")
    assert len(db.payments.list_for_claim("c1")) == 1


def test_eob_uses_existing_decisions_and_does_not_readjudicate(
    db: SqliteDatabase,
) -> None:
    _seed(db)
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="PHYSIO-30")),
    )
    decision_before = db.decisions.list_for_line("c1-L1")
    _pay(db, "c1", 4_000)
    eob = build_eob(db, "c1")
    assert db.decisions.list_for_line("c1-L1") == decision_before
    assert eob.claim_id == "c1"
    assert eob.settlement_state == SettlementState.SETTLED.value
    assert eob.payable_minor == 4_000
    assert eob.paid_minor == 4_000
    assert eob.billed_minor == 5_000
    assert eob.member_responsibility_minor == 1_000
    line = eob.lines[0]
    assert line.outcome == "APPROVED"
    assert line.amounts is not None
    assert line.amounts.plan_paid_minor == 4_000
    codes = {item.code for item in line.explanations}
    assert "MEM_ABOVE_ALLOWED" in codes
    assert "INFO_COVERED" in codes
    assert any(
        item.message == get_reason(ReasonCodeId.INFO_COVERED).message
        for item in line.explanations
    )
    assert len(eob.payments) == 1
    assert eob.payments[0].amount_minor == 4_000


def test_overpaid_claim_ledger_allows_subsequent_claim_on_same_benefit(
    db: SqliteDatabase,
) -> None:
    """After appeal reduces payable below paid, ledger reflects current adjudication for limit checks."""
    from app.domain.accumulators import AccumulatorKey, AccumulatorScope
    from app.domain.states import LineOutcome

    _seed(db, limit=6_000)
    submit_claim(
        db,
        Claim(
            id="c1",
            member_id="m1",
            submitted_at=datetime(2026, 3, 20, 10, 0),
            lines=(
                ClaimLine(
                    id="c1-L1",
                    claim_id="c1",
                    line_number=1,
                    provider_id="prov1",
                    service_code="PHYSIO-30",
                    service_date=date(2026, 3, 15),
                    billed_amount=Money(5_000),
                    diagnosis_code="M54.5",
                ),
                ClaimLine(
                    id="c1-L2",
                    claim_id="c1",
                    line_number=2,
                    provider_id="prov1",
                    service_code="PHYSIO-30",
                    service_date=date(2026, 3, 16),
                    billed_amount=Money(5_000),
                    diagnosis_code="M54.5",
                ),
            ),
        ),
    )
    record_payment(db, claim_id="c1", amount=Money(6_000), reference="pay1")
    assert get_claim(db, "c1").settlement_state == SettlementState.SETTLED.value

    file_dispute(db, claim_id="c1", line_number=2, member_reason="wrong code")
    resolve_review(
        db,
        line_id="c1-L2",
        mode=ReviewResolutionMode.CORRECT_FACTS,
        reviewer_id="rev1",
        note="excluded",
        corrections=LineFactCorrections(service_code="COSMETIC-1"),
    )
    overpaid = get_claim(db, "c1")
    assert overpaid.settlement_state == SettlementState.OVERPAID.value
    assert overpaid.payable_minor == 4_000
    paid_total = sum(p.amount.minor_units for p in db.payments.list_for_claim("c1"))
    assert paid_total == 6_000

    amount_key = AccumulatorKey(
        member_id="m1",
        plan_year=2026,
        scope=AccumulatorScope.BENEFIT_AMOUNT,
        benefit_code="PHYSIO",
    )
    assert db.accumulators.balance(amount_key) == 4_000

    result = submit_claim(
        db,
        Claim(
            id="c2",
            member_id="m1",
            submitted_at=datetime(2026, 3, 25, 10, 0),
            lines=(
                ClaimLine(
                    id="c2-L1",
                    claim_id="c2",
                    line_number=1,
                    provider_id="prov1",
                    service_code="PHYSIO-30",
                    service_date=date(2026, 3, 20),
                    billed_amount=Money(5_000),
                    diagnosis_code="M54.5",
                ),
            ),
        ),
    )
    assert result.line_decisions[0].outcome is LineOutcome.PARTIALLY_APPROVED
    assert result.payable == Money(2_000)
    assert db.accumulators.balance(amount_key) == 6_000


def test_all_lines_needs_review_blocks_payment_with_nothing_due(
    db: SqliteDatabase,
) -> None:
    _seed(db)
    submit_claim(
        db,
        Claim(
            id="review-all",
            member_id="m1",
            submitted_at=datetime(2026, 3, 20, 10, 0),
            lines=(
                ClaimLine(
                    id="review-all-L1",
                    claim_id="review-all",
                    line_number=1,
                    provider_id="prov1",
                    service_code="NOT-IN-CATALOG",
                    service_date=date(2026, 3, 15),
                    billed_amount=Money(1_000),
                    diagnosis_code="M54.5",
                ),
                ClaimLine(
                    id="review-all-L2",
                    claim_id="review-all",
                    line_number=2,
                    provider_id="prov1",
                    service_code="NOT-IN-CATALOG",
                    service_date=date(2026, 3, 16),
                    billed_amount=Money(2_000),
                    diagnosis_code="M54.5",
                ),
            ),
        ),
    )
    view = get_claim(db, "review-all")
    assert view.adjudication_state == ClaimAdjudicationState.UNDER_REVIEW.value
    assert view.payable_minor == 0
    assert view.settlement_state == SettlementState.NOTHING_DUE.value

    with pytest.raises(PaymentWhileUnderReviewError):
        record_payment(
            db,
            claim_id="review-all",
            amount=Money(1),
            reference="should-fail",
        )
