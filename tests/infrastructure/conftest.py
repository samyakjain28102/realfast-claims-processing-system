from datetime import date, datetime

import pytest

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


@pytest.fixture
def member() -> Member:
    return Member(id="m1", name="Ada Lovelace", date_of_birth=date(1990, 1, 1))


@pytest.fixture
def provider() -> Provider:
    return Provider(id="prov1", name="City Clinic")


@pytest.fixture
def benefit() -> Benefit:
    return Benefit(
        code="PHYSIO",
        name="Physiotherapy",
        covered=True,
        excluded=False,
        annual_limit_amount=Money(100_000),
        annual_visit_limit=12,
    )


@pytest.fixture
def plan(benefit: Benefit) -> Plan:
    return Plan(id="plan1", version=2, deductible=Money(10_000), benefits=(benefit,))


@pytest.fixture
def policy() -> Policy:
    return Policy(
        id="pol1",
        member_id="m1",
        plan_id="plan1",
        effective_date=date(2026, 1, 1),
        termination_date=None,
    )


@pytest.fixture
def catalogue_entry() -> ServiceCatalogueEntry:
    return ServiceCatalogueEntry(
        service_code="PHYSIO-30",
        description="Physio session",
        benefit_code="PHYSIO",
        scheduled_amount=Money(4_000),
    )


@pytest.fixture
def claim_line() -> ClaimLine:
    return ClaimLine(
        id="claim1-L1",
        claim_id="claim1",
        line_number=1,
        provider_id="prov1",
        service_code="PHYSIO-30",
        service_date=date(2026, 3, 15),
        billed_amount=Money(5_000),
        diagnosis_code="M54.5",
    )


@pytest.fixture
def claim(claim_line: ClaimLine) -> Claim:
    return Claim(
        id="claim1",
        member_id="m1",
        submitted_at=datetime(2026, 3, 20, 10, 0),
        lines=(claim_line,),
    )


@pytest.fixture
def seeded_db(
    db: SqliteDatabase,
    member: Member,
    provider: Provider,
    plan: Plan,
    policy: Policy,
    catalogue_entry: ServiceCatalogueEntry,
) -> SqliteDatabase:
    db.members.add(member)
    db.providers.add(provider)
    db.plans.add(plan)
    db.policies.add(policy)
    db.catalogue.add(catalogue_entry)
    return db
