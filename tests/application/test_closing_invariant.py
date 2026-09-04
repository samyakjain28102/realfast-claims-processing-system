"""Application tests for closing invariant rollback on submit."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch

import pytest

from app.application.submit_claim import (
    AccumulatorLimitExceededError,
    submit_claim,
)
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
from app.domain.rules import Benefit
from app.infrastructure.db import SqliteDatabase, open_database


@pytest.fixture
def db() -> SqliteDatabase:
    database = open_database()
    yield database
    database.close()


def _seed(db: SqliteDatabase) -> None:
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


def _amount_key() -> AccumulatorKey:
    return AccumulatorKey(
        member_id="m1",
        plan_year=2026,
        scope=AccumulatorScope.BENEFIT_AMOUNT,
        benefit_code="PHYSIO",
    )


def test_closing_invariant_failure_rolls_back_persisted_rows(db: SqliteDatabase) -> None:
    _seed(db)
    balance_before = db.accumulators.balance(_amount_key())
    claim = Claim(
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
        ),
    )
    with patch(
        "app.application.submit_claim._assert_within_limits",
        side_effect=AccumulatorLimitExceededError("simulated invariant breach"),
    ):
        with pytest.raises(AccumulatorLimitExceededError):
            submit_claim(db, claim)

    assert db.claims.get("c1") is None
    assert db.decisions.current_for_line("c1-L1") is None
    assert db.accumulators.balance(_amount_key()) == balance_before
