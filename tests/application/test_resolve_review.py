"""Application tests for iterative NEEDS_REVIEW resolution."""

from __future__ import annotations

from datetime import date, datetime

import pytest
import sqlite3

from app.application.resolve_review import (
    LineNotInReviewError,
    UpholdNotAllowedError,
    resolve_review,
)
from app.application.submit_claim import submit_claim
from app.domain.accumulators import AccumulatorKey, AccumulatorScope
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
from app.domain.reasons import ReasonCodeId
from app.domain.rules import Benefit
from app.domain.states import (
    ClaimAdjudicationState,
    LineOutcome,
    ReviewResolutionMode,
)
from app.infrastructure.db import SqliteDatabase, open_database


@pytest.fixture
def db() -> SqliteDatabase:
    database = open_database()
    yield database
    database.close()


def _physio(limit: int = 10_000, visits: int = 12) -> Benefit:
    return Benefit(
        code="PHYSIO",
        name="Physiotherapy",
        covered=True,
        excluded=False,
        annual_limit_amount=Money(limit),
        annual_visit_limit=visits,
    )


def _seed(
    db: SqliteDatabase,
    *,
    deductible: int = 0,
    limit: int = 10_000,
    plan_version: int = 1,
    policy_effective: date = date(2025, 1, 1),
) -> None:
    db.members.add(Member(id="m1", name="Ada", date_of_birth=date(1990, 1, 1)))
    db.providers.add(Provider(id="prov1", name="City Clinic"))
    db.plans.add(
        Plan(
            id="plan1",
            version=plan_version,
            deductible=Money(deductible),
            benefits=(_physio(limit=limit),),
        )
    )
    db.policies.add(
        Policy(
            id="pol1",
            member_id="m1",
            plan_id="plan1",
            effective_date=policy_effective,
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
    number: int,
    *,
    service_code: str,
    service_date: date,
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


def _correct(
    db: SqliteDatabase,
    line_id: str,
    corrections: LineFactCorrections,
    *,
    reviewer_id: str = "rev1",
    note: str = "correct facts",
    decided_at: datetime | None = None,
):
    return resolve_review(
        db,
        line_id=line_id,
        mode=ReviewResolutionMode.CORRECT_FACTS,
        reviewer_id=reviewer_id,
        note=note,
        corrections=corrections,
        decided_at=decided_at or datetime(2026, 3, 21, 9, 0),
    )


def _amount_key(plan_year: int) -> AccumulatorKey:
    return AccumulatorKey(
        member_id="m1",
        plan_year=plan_year,
        scope=AccumulatorScope.BENEFIT_AMOUNT,
        benefit_code="PHYSIO",
    )


def _visit_key(plan_year: int) -> AccumulatorKey:
    return AccumulatorKey(
        member_id="m1",
        plan_year=plan_year,
        scope=AccumulatorScope.BENEFIT_VISITS,
        benefit_code="PHYSIO",
    )


def test_unknown_service_corrected_to_known_service_is_approved(
    db: SqliteDatabase,
) -> None:
    _seed(db)
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="NOT-IN-CATALOG", service_date=date(2026, 3, 15))),
    )
    first = db.decisions.current_for_line("c1-L1")
    assert first is not None
    assert first.outcome is LineOutcome.NEEDS_REVIEW
    assert first.plan_version == 1
    assert db.accumulators.balance(_amount_key(2026)) == 0

    db.plans.add(
        Plan(
            id="plan1",
            version=2,
            deductible=Money(99_000),
            benefits=(_physio(limit=1),),
        )
    )

    result = _correct(db, "c1-L1", LineFactCorrections(service_code="PHYSIO-30"))

    assert result.adjudication_state is ClaimAdjudicationState.APPROVED
    current = db.decisions.current_for_line("c1-L1")
    assert current is not None
    assert current.id != first.id
    assert current.sequence == 2
    assert current.source.value == "RULES"
    assert current.outcome is LineOutcome.APPROVED
    assert current.plan_version == 1
    assert current.amounts is not None
    assert current.amounts.plan_paid == Money(4_000)
    assert db.accumulators.balance(_amount_key(2026)) == 4_000
    assert db.accumulators.balance(_visit_key(2026)) == 1
    resolutions = db.reviews.list_for_line("c1-L1")
    assert len(resolutions) == 1
    assert resolutions[0].mode is ReviewResolutionMode.CORRECT_FACTS
    assert resolutions[0].resulting_decision_id == current.id


def test_first_correction_still_needs_review_second_correction_approves(
    db: SqliteDatabase,
) -> None:
    _seed(db)
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="NOT-IN-CATALOG", service_date=date(2026, 3, 15))),
    )

    first = _correct(
        db,
        "c1-L1",
        LineFactCorrections(service_code="STILL-UNKNOWN"),
        note="first attempt",
        decided_at=datetime(2026, 3, 21, 9, 0),
    )
    mid = db.decisions.current_for_line("c1-L1")
    assert first.adjudication_state is ClaimAdjudicationState.UNDER_REVIEW
    assert mid is not None
    assert mid.sequence == 2
    assert mid.outcome is LineOutcome.NEEDS_REVIEW
    assert ReasonCodeId.REV_UNKNOWN_SERVICE in mid.reasons
    assert db.accumulators.balance(_amount_key(2026)) == 0
    assert len(db.reviews.list_for_line("c1-L1")) == 1

    second = _correct(
        db,
        "c1-L1",
        LineFactCorrections(service_code="PHYSIO-30"),
        note="second attempt",
        decided_at=datetime(2026, 3, 21, 10, 0),
    )
    final = db.decisions.current_for_line("c1-L1")
    assert second.adjudication_state is ClaimAdjudicationState.APPROVED
    assert final is not None
    assert final.sequence == 3
    assert final.outcome is LineOutcome.APPROVED
    assert db.accumulators.balance(_amount_key(2026)) == 4_000
    assert len(db.reviews.list_for_line("c1-L1")) == 2


def test_previous_decisions_remain_immutable_after_resolution(
    db: SqliteDatabase,
) -> None:
    _seed(db)
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="NOT-IN-CATALOG", service_date=date(2026, 3, 15))),
    )
    original = db.decisions.current_for_line("c1-L1")
    assert original is not None
    original_snapshot = db.decisions.get(original.id)

    _correct(db, "c1-L1", LineFactCorrections(service_code="PHYSIO-30"))

    stored = db.decisions.get(original.id)
    assert stored == original_snapshot
    history = db.decisions.list_for_line("c1-L1")
    assert len(history) == 2
    assert history[0] == original_snapshot
    assert history[1].sequence == 2

    with pytest.raises(sqlite3.Error, match="append-only"):
        db.connection.execute(
            "UPDATE line_decisions SET outcome = ? WHERE id = ?",
            (LineOutcome.DENIED.value, original.id),
        )


def test_uphold_without_dispute_is_rejected(db: SqliteDatabase) -> None:
    _seed(db)
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="NOT-IN-CATALOG", service_date=date(2026, 3, 15))),
    )
    with pytest.raises(UpholdNotAllowedError):
        resolve_review(
            db,
            line_id="c1-L1",
            mode=ReviewResolutionMode.UPHOLD,
            reviewer_id="rev1",
            note="uphold without facts",
        )
    assert db.decisions.current_for_line("c1-L1") is not None
    assert db.decisions.current_for_line("c1-L1").sequence == 1
    assert db.reviews.list_for_line("c1-L1") == ()


def test_terminal_line_cannot_be_resolved_without_review(
    db: SqliteDatabase,
) -> None:
    _seed(db)
    submit_claim(
        db,
        _claim("c1", _line("c1", 1, service_code="PHYSIO-30", service_date=date(2026, 3, 15))),
    )
    with pytest.raises(LineNotInReviewError):
        _correct(db, "c1-L1", LineFactCorrections(service_code="PHYSIO-30"))


def test_correction_changing_plan_year_reverses_old_key_and_posts_new(
    db: SqliteDatabase,
) -> None:
    _seed(db, policy_effective=date(2025, 1, 1))
    submit_claim(
        db,
        _claim(
            "c1",
            _line("c1", 1, service_code="NOT-IN-CATALOG", service_date=date(2026, 3, 15)),
            _line("c1", 2, service_code="PHYSIO-30", service_date=date(2026, 3, 16)),
        ),
    )
    sibling_first = db.decisions.current_for_line("c1-L2")
    assert sibling_first is not None
    assert db.accumulators.balance(_amount_key(2026)) == 4_000
    assert db.accumulators.balance(_amount_key(2025)) == 0
    old_sibling_entries = db.accumulators.list_for_decision(sibling_first.id)
    assert old_sibling_entries

    result = _correct(
        db,
        "c1-L1",
        LineFactCorrections(
            service_code="PHYSIO-30",
            service_date=date(2025, 6, 1),
        ),
    )

    assert result.adjudication_state is ClaimAdjudicationState.APPROVED
    stored = db.claims.get("c1")
    assert stored is not None
    assert stored.claim.lines[0].service_date == date(2025, 6, 1)

    review_current = db.decisions.current_for_line("c1-L1")
    sibling_current = db.decisions.current_for_line("c1-L2")
    assert review_current is not None
    assert sibling_current is not None
    assert review_current.sequence == 2
    assert sibling_current.sequence == 2
    assert sibling_current.id != sibling_first.id
    assert sibling_first.outcome is LineOutcome.APPROVED

    assert db.accumulators.balance(_amount_key(2025)) == 4_000
    assert db.accumulators.balance(_visit_key(2025)) == 1
    assert db.accumulators.balance(_amount_key(2026)) == 4_000
    assert db.accumulators.balance(_visit_key(2026)) == 1

    reversals = [
        entry
        for entry in db.accumulators.list_for_decision(sibling_current.id)
        if entry.reverses_entry_id is not None
    ]
    assert {entry.reverses_entry_id for entry in reversals} == {
        entry.id for entry in old_sibling_entries
    }
    assert all(entry.key.plan_year == 2026 for entry in reversals)
    assert all(
        db.accumulators.is_reversed(entry.id) for entry in old_sibling_entries
    )
    new_year_entries = db.accumulators.list_for_decision(review_current.id)
    assert new_year_entries
    assert all(entry.key.plan_year == 2025 for entry in new_year_entries)
    assert all(entry.reverses_entry_id is None for entry in new_year_entries)


def test_whole_claim_readjudication_changes_terminal_sibling(
    db: SqliteDatabase,
) -> None:
    _seed(db, limit=6_000)
    submit_claim(
        db,
        _claim(
            "c1",
            _line("c1", 1, service_code="NOT-IN-CATALOG", service_date=date(2026, 3, 15)),
            _line("c1", 2, service_code="PHYSIO-30", service_date=date(2026, 3, 16)),
        ),
    )
    sibling_first = db.decisions.current_for_line("c1-L2")
    assert sibling_first is not None
    assert sibling_first.outcome is LineOutcome.APPROVED
    assert sibling_first.amounts is not None
    assert sibling_first.amounts.plan_paid == Money(4_000)
    assert db.accumulators.balance(_amount_key(2026)) == 4_000

    result = _correct(db, "c1-L1", LineFactCorrections(service_code="PHYSIO-30"))

    assert result.adjudication_state is ClaimAdjudicationState.PARTIALLY_APPROVED
    review = db.decisions.current_for_line("c1-L1")
    sibling = db.decisions.current_for_line("c1-L2")
    assert review is not None
    assert sibling is not None
    assert review.outcome is LineOutcome.APPROVED
    assert review.amounts is not None
    assert review.amounts.plan_paid == Money(4_000)
    assert sibling.sequence == 2
    assert sibling.outcome is LineOutcome.PARTIALLY_APPROVED
    assert sibling.amounts is not None
    assert sibling.amounts.plan_paid == Money(2_000)
    assert ReasonCodeId.DEN_ANNUAL_LIMIT in sibling.reasons
    assert sibling_first.amounts.plan_paid == Money(4_000)
    assert db.decisions.get(sibling_first.id) == sibling_first
    assert db.accumulators.balance(_amount_key(2026)) == 6_000
    assert db.accumulators.balance(_visit_key(2026)) == 2
