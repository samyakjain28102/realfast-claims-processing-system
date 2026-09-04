"""Demo-ready reference data for API tests and local runs."""

from __future__ import annotations

from datetime import date

from app.domain.entities import (
    Member,
    Plan,
    Policy,
    Provider,
    ServiceCatalogueEntry,
)
from app.domain.money import Money
from app.domain.rules import Benefit
from app.infrastructure.db import SqliteDatabase


def load_reference_data(db: SqliteDatabase) -> None:
    """Seed members, plan, policy, providers, and service catalogue."""
    physio = Benefit(
        code="PHYSIO",
        name="Physiotherapy",
        covered=True,
        excluded=False,
        annual_limit_amount=Money(10_000),
        annual_visit_limit=12,
    )
    cosmetic = Benefit(
        code="COSMETIC",
        name="Cosmetic procedures",
        covered=True,
        excluded=True,
        annual_limit_amount=None,
        annual_visit_limit=None,
    )
    db.members.add(
        Member(id="m1", name="Ada Lovelace", date_of_birth=date(1990, 1, 1))
    )
    db.providers.add(Provider(id="prov1", name="City Clinic"))
    db.plans.add(
        Plan(
            id="plan1",
            version=1,
            deductible=Money(10_000),
            benefits=(physio, cosmetic),
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
    for entry in (
        ServiceCatalogueEntry(
            service_code="PHYSIO-30",
            description="Physio session",
            benefit_code="PHYSIO",
            scheduled_amount=Money(4_000),
        ),
        ServiceCatalogueEntry(
            service_code="COSMETIC-1",
            description="Cosmetic procedure",
            benefit_code="COSMETIC",
            scheduled_amount=Money(10_000),
        ),
    ):
        db.catalogue.add(entry)
