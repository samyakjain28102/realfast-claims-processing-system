"""Threaded integration tests for concurrent limit consumption (technical-plan §4.1)."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from unittest.mock import patch

import pytest

from app.application.submit_claim import submit_claim
from app.domain.accumulators import AccumulatorKey, AccumulatorScope
from app.domain.entities import (
    Claim,
    ClaimLine,
    Member,
    Plan,
    Policy,
    Provider,
    ServiceCatalogueEntry,
)
from app.domain.money import Money
from app.domain.reasons import ReasonCodeId
from app.domain.rules import Benefit
from app.domain.states import LineOutcome
from app.infrastructure.db import (
    SqliteDatabase,
    connect_shared_memory,
    open_shared_memory,
)

ANNUAL_LIMIT = 10_000
PRIOR_CONSUMED = 8_000
REMAINING = ANNUAL_LIMIT - PRIOR_CONSUMED


def _amount_key(*, member_id: str = "m1", plan_year: int = 2026) -> AccumulatorKey:
    return AccumulatorKey(
        member_id=member_id,
        plan_year=plan_year,
        scope=AccumulatorScope.BENEFIT_AMOUNT,
        benefit_code="PHYSIO",
    )


def _seed_reference(db: SqliteDatabase) -> None:
    benefit = Benefit(
        code="PHYSIO",
        name="Physiotherapy",
        covered=True,
        excluded=False,
        annual_limit_amount=Money(ANNUAL_LIMIT),
        annual_visit_limit=12,
    )
    db.members.add(Member(id="m1", name="Ada", date_of_birth=date(1990, 1, 1)))
    db.providers.add(Provider(id="prov1", name="City Clinic"))
    db.plans.add(
        Plan(id="plan1", version=1, deductible=Money.zero(), benefits=(benefit,))
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


def _line(
    claim_id: str,
    *,
    service_date: date,
    line_number: int = 1,
) -> ClaimLine:
    return ClaimLine(
        id=f"{claim_id}-L{line_number}",
        claim_id=claim_id,
        line_number=line_number,
        provider_id="prov1",
        service_code="PHYSIO-30",
        service_date=service_date,
        billed_amount=Money(5_000),
        diagnosis_code="M54.5",
    )


def _claim(
    claim_id: str,
    service_date: date,
    *,
    submitted_at: datetime | None = None,
) -> Claim:
    return Claim(
        id=claim_id,
        member_id="m1",
        submitted_at=submitted_at
        or datetime.combine(service_date, datetime.min.time()).replace(
            hour=12, minute=0
        ),
        lines=(_line(claim_id, service_date=service_date),),
    )


def _seed_prior_consumption(db: SqliteDatabase) -> None:
    """Two approved physio lines consume ₹8,000 of the ₹10,000 annual limit."""
    submit_claim(
        db,
        Claim(
            id="prior",
            member_id="m1",
            submitted_at=datetime(2026, 3, 20, 9, 0),
            lines=(
                _line("prior", service_date=date(2026, 3, 1), line_number=1),
                _line("prior", service_date=date(2026, 3, 2), line_number=2),
            ),
        ),
    )
    assert db.accumulators.balance(_amount_key()) == PRIOR_CONSUMED


def test_concurrent_claims_do_not_overspend_annual_limit() -> None:
    """Two claims racing for ₹2,000 remaining must not exceed the benefit limit."""
    memory_name = f"concurrency-{uuid.uuid4().hex}"
    primary = open_shared_memory(name=memory_name)
    secondary = connect_shared_memory(name=memory_name)
    try:
        _seed_reference(primary)
        _seed_prior_consumption(primary)

        claim_a = _claim(
            "claim-a",
            service_date=date(2026, 3, 20),
            submitted_at=datetime(2026, 3, 25, 10, 0),
        )
        claim_b = _claim(
            "claim-b",
            service_date=date(2026, 3, 21),
            submitted_at=datetime(2026, 3, 25, 10, 0),
        )
        start = threading.Barrier(2)

        def submit_after_sync(db: SqliteDatabase, claim: Claim):
            start.wait(timeout=5)
            return submit_claim(db, claim)

        with ThreadPoolExecutor(max_workers=2) as pool:
            future_a = pool.submit(submit_after_sync, primary, claim_a)
            future_b = pool.submit(submit_after_sync, secondary, claim_b)
            result_a = future_a.result(timeout=30)
            result_b = future_b.result(timeout=30)

        results = (result_a, result_b)
        total_new_plan_paid = sum(result.payable.minor_units for result in results)
        assert total_new_plan_paid <= REMAINING
        assert total_new_plan_paid == REMAINING

        partial = [
            result
            for result in results
            if result.line_decisions[0].outcome is LineOutcome.PARTIALLY_APPROVED
        ]
        denied = [
            result
            for result in results
            if result.line_decisions[0].outcome is LineOutcome.DENIED
        ]
        assert len(partial) == 1
        assert len(denied) == 1
        assert partial[0].payable == Money(REMAINING)
        assert denied[0].payable == Money.zero()
        assert ReasonCodeId.DEN_ANNUAL_LIMIT in partial[0].line_decisions[0].reasons
        assert ReasonCodeId.DEN_ANNUAL_LIMIT in denied[0].line_decisions[0].reasons

        final_balance = primary.accumulators.balance(_amount_key())
        assert final_balance == ANNUAL_LIMIT
        assert secondary.accumulators.balance(_amount_key()) == ANNUAL_LIMIT

        prior_payable = Money(PRIOR_CONSUMED)
        combined = prior_payable + Money(total_new_plan_paid)
        assert combined == Money(ANNUAL_LIMIT)
    finally:
        primary.close()
        secondary.close()


def test_submit_claim_retries_begin_immediate_with_full_re_adjudication(
    db: SqliteDatabase,
) -> None:
    """A lock on BEGIN IMMEDIATE must re-run adjudication, not reuse a stale result."""
    _seed_reference(db)
    _seed_prior_consumption(db)

    claim = _claim(
        "after-lock",
        service_date=date(2026, 3, 25),
        submitted_at=datetime(2026, 3, 25, 10, 0),
    )
    attempts = 0
    original_begin = db.begin_immediate

    def flaky_begin() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        original_begin()

    with patch.object(db, "begin_immediate", side_effect=flaky_begin):
        result = submit_claim(db, claim)

    assert attempts == 2
    assert result.payable == Money(REMAINING)
    assert result.line_decisions[0].outcome is LineOutcome.PARTIALLY_APPROVED
    assert db.accumulators.balance(_amount_key()) == ANNUAL_LIMIT


@pytest.fixture
def db() -> SqliteDatabase:
    from app.infrastructure.db import open_database

    database = open_database()
    yield database
    database.close()
