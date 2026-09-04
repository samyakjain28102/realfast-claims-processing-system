"""Application tests for submit_claim against in-memory SQLite."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pytest

from app.application.submit_claim import (
    MemberNotFoundError,
    ProviderNotFoundError,
    submit_claim,
)
from app.domain.entities import (
    Claim,
    ClaimLine,
    Member,
    Plan,
    Policy,
    Provider,
    ServiceCatalogueEntry,
)
from app.domain.accumulators import AccumulatorKey, AccumulatorScope
from app.domain.money import Money
from app.domain.reasons import ReasonCodeId
from app.domain.rules import Benefit
from app.domain.states import (
    ClaimAdjudicationState,
    LineOutcome,
    SettlementState,
)
from app.domain.accumulators import AccumulatorKey, AccumulatorScope
from app.infrastructure.db import SqliteDatabase, open_database


@pytest.fixture
def db() -> SqliteDatabase:
    database = open_database()
    yield database
    database.close()


def _seed_reference(db: SqliteDatabase) -> None:
    benefit = Benefit(
        code="PHYSIO",
        name="Physiotherapy",
        covered=True,
        excluded=False,
        annual_limit_amount=Money(10_000),
        annual_visit_limit=12,
    )
    db.members.add(Member(id="m1", name="Ada", date_of_birth=date(1990, 1, 1)))
    db.providers.add(Provider(id="prov1", name="City Clinic"))
    db.plans.add(
        Plan(id="plan1", version=2, deductible=Money.zero(), benefits=(benefit,))
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


def _claim(
    *,
    claim_id: str = "claim1",
    service_code: str = "PHYSIO-30",
    billed: int = 5_000,
    line_id: str | None = None,
) -> Claim:
    line_id = line_id or f"{claim_id}-L1"
    return Claim(
        id=claim_id,
        member_id="m1",
        submitted_at=datetime(2026, 3, 20, 10, 0),
        lines=(
            ClaimLine(
                id=line_id,
                claim_id=claim_id,
                line_number=1,
                provider_id="prov1",
                service_code=service_code,
                service_date=date(2026, 3, 15),
                billed_amount=Money(billed),
                diagnosis_code="M54.5",
            ),
        ),
    )


def test_submit_claim_persists_decisions_and_terminal_ledger_entries(
    db: SqliteDatabase,
) -> None:
    _seed_reference(db)
    claim = _claim(billed=5_000)
    result = submit_claim(db, claim)

    assert result.rejected is False
    assert result.adjudication_state is ClaimAdjudicationState.APPROVED
    assert result.settlement_state is SettlementState.DUE
    assert result.payable == Money(4_000)
    assert len(result.line_decisions) == 1
    assert result.line_decisions[0].outcome is LineOutcome.APPROVED

    stored = db.claims.get("claim1")
    assert stored is not None
    assert stored.rejected is False
    assert db.decisions.list_for_claim("claim1")
    key = AccumulatorKey(
        member_id="m1",
        plan_year=2026,
        scope=AccumulatorScope.BENEFIT_AMOUNT,
        benefit_code="PHYSIO",
    )
    assert db.accumulators.balance(key) == 4_000


def test_submit_claim_rejected_claim_persists_without_decisions_or_ledger(
    db: SqliteDatabase,
) -> None:
    _seed_reference(db)
    claim = Claim(
        id="claim-bad",
        member_id="m1",
        submitted_at=datetime(2026, 3, 20, 10, 0),
        lines=(),
    )
    result = submit_claim(db, claim)

    assert result.rejected is True
    assert result.rejection_reason is ReasonCodeId.REJ_INVALID_CLAIM
    assert result.adjudication_state is ClaimAdjudicationState.REJECTED
    assert result.line_decisions == ()
    stored = db.claims.get("claim-bad")
    assert stored is not None
    assert stored.rejected is True
    assert db.decisions.list_for_claim("claim-bad") == ()


def test_needs_review_line_posts_no_ledger_while_terminal_sibling_does(
    db: SqliteDatabase,
) -> None:
    _seed_reference(db)
    claim = Claim(
        id="claim-mixed",
        member_id="m1",
        submitted_at=datetime(2026, 3, 20, 10, 0),
        lines=(
            ClaimLine(
                id="claim-mixed-L1",
                claim_id="claim-mixed",
                line_number=1,
                provider_id="prov1",
                service_code="NOT-IN-CATALOGUE",
                service_date=date(2026, 3, 15),
                billed_amount=Money(1_000),
                diagnosis_code="M54.5",
            ),
            ClaimLine(
                id="claim-mixed-L2",
                claim_id="claim-mixed",
                line_number=2,
                provider_id="prov1",
                service_code="PHYSIO-30",
                service_date=date(2026, 3, 16),
                billed_amount=Money(5_000),
                diagnosis_code="M54.5",
            ),
        ),
    )
    result = submit_claim(db, claim)

    assert result.adjudication_state is ClaimAdjudicationState.UNDER_REVIEW
    assert result.payable == Money(4_000)
    review_decision = db.decisions.current_for_line("claim-mixed-L1")
    assert review_decision is not None
    assert review_decision.outcome is LineOutcome.NEEDS_REVIEW
    assert not any(
        entry.decision_id == review_decision.id
        for entry in db.accumulators.list_for_key(
            AccumulatorKey(
                member_id="m1",
                plan_year=2026,
                scope=AccumulatorScope.BENEFIT_AMOUNT,
                benefit_code="PHYSIO",
            )
        )
    )
    approved = db.decisions.current_for_line("claim-mixed-L2")
    assert approved is not None
    assert approved.amounts is not None
    assert approved.amounts.plan_paid == Money(4_000)


def test_second_claim_sees_prior_terminal_line_as_suspected_duplicate(
    db: SqliteDatabase,
) -> None:
    _seed_reference(db)
    first = _claim(claim_id="claim-a")
    submit_claim(db, first)
    second = _claim(claim_id="claim-b", line_id="claim-b-L1")
    result = submit_claim(db, second)

    assert result.adjudication_state is ClaimAdjudicationState.UNDER_REVIEW
    decision = result.line_decisions[0]
    assert decision.outcome is LineOutcome.NEEDS_REVIEW
    assert ReasonCodeId.REV_SUSPECTED_DUPLICATE in decision.reasons


def test_submit_claim_rejects_unknown_member(db: SqliteDatabase) -> None:
    _seed_reference(db)
    claim = _claim()
    unknown = Claim(
        id="claim-x",
        member_id="missing",
        submitted_at=claim.submitted_at,
        lines=(
            ClaimLine(
                id="claim-x-L1",
                claim_id="claim-x",
                line_number=1,
                provider_id="prov1",
                service_code="PHYSIO-30",
                service_date=date(2026, 3, 15),
                billed_amount=Money(5_000),
                diagnosis_code="M54.5",
            ),
        ),
    )
    with pytest.raises(MemberNotFoundError):
        submit_claim(db, unknown)


def test_submit_claim_rejects_unknown_provider(db: SqliteDatabase) -> None:
    _seed_reference(db)
    claim = Claim(
        id="claim-y",
        member_id="m1",
        submitted_at=datetime(2026, 3, 20, 10, 0),
        lines=(
            ClaimLine(
                id="claim-y-L1",
                claim_id="claim-y",
                line_number=1,
                provider_id="missing-prov",
                service_code="PHYSIO-30",
                service_date=date(2026, 3, 15),
                billed_amount=Money(5_000),
                diagnosis_code="M54.5",
            ),
        ),
    )
    with pytest.raises(ProviderNotFoundError):
        submit_claim(db, claim)


def test_failed_transaction_leaves_no_orphan_decisions_or_ledger_rows(
    db: SqliteDatabase,
) -> None:
    _seed_reference(db)
    claim = _claim()
    original_add = db.accumulators.add

    def fail_on_second_entry(entry):  # type: ignore[no-untyped-def]
        if db.connection.execute(
            "SELECT COUNT(*) AS n FROM accumulator_entries"
        ).fetchone()["n"]:
            raise RuntimeError("simulated persistence failure")
        original_add(entry)

    with patch.object(db.accumulators, "add", side_effect=fail_on_second_entry):
        with pytest.raises(RuntimeError, match="simulated persistence failure"):
            submit_claim(db, claim)

    assert db.claims.get("claim1") is None
    assert db.decisions.list_for_claim("claim1") == ()
    assert (
        db.connection.execute(
            "SELECT COUNT(*) AS n FROM accumulator_entries"
        ).fetchone()["n"]
        == 0
    )
