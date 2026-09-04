"""Round-trip persistence of domain objects through SQLite repositories."""

from __future__ import annotations

import ast
from datetime import date, datetime
from pathlib import Path

import pytest
import sqlite3

from app.domain.accumulators import (
    AccumulatorEntry,
    AccumulatorKey,
    AccumulatorScope,
    compensating_entry,
)
from app.domain.entities import (
    Claim,
    ClaimLine,
    DecisionAmounts,
    Dispute,
    LineDecision,
    LineFactCorrections,
    Payment,
    Plan,
    Policy,
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
from app.infrastructure.db import SqliteDatabase, open_database


STORED_STATE_COLUMNS = frozenset(
    {
        "adjudication_state",
        "settlement_state",
        "line_state",
        "payable",
        "paid",
        "balance",
    }
)


def _decision(
    *,
    decision_id: str = "dec1",
    line_id: str = "claim1-L1",
    sequence: int = 1,
    outcome: LineOutcome = LineOutcome.APPROVED,
    amounts: DecisionAmounts | None = None,
    reasons: tuple[ReasonCodeId, ...] = (ReasonCodeId.INFO_COVERED,),
    trace: tuple[TraceStep, ...] = (),
) -> LineDecision:
    return LineDecision(
        id=decision_id,
        line_id=line_id,
        sequence=sequence,
        source=DecisionSource.RULES,
        outcome=outcome,
        reasons=reasons,
        trace=trace,
        plan_version=2,
        decided_at=datetime(2026, 3, 20, 10, 1),
        decided_by="rules",
        amounts=amounts,
    )


def test_in_memory_database_creates_expected_tables(db: SqliteDatabase) -> None:
    names = {
        row["name"]
        for row in db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert names >= {
        "members",
        "providers",
        "plans",
        "benefits",
        "policies",
        "service_catalogue",
        "claims",
        "claim_lines",
        "line_decisions",
        "accumulator_entries",
        "payments",
        "disputes",
        "review_resolutions",
    }


def test_schema_does_not_store_derived_states(db: SqliteDatabase) -> None:
    columns = {
        row["name"]
        for row in db.connection.execute(
            "SELECT name FROM pragma_table_info('claims')"
        )
    }
    assert columns.isdisjoint(STORED_STATE_COLUMNS)
    assert "rejected" in columns


def test_file_database_enables_wal_and_foreign_keys(tmp_path: Path) -> None:
    path = tmp_path / "claims.sqlite3"
    database = open_database(str(path))
    try:
        journal = database.connection.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = database.connection.execute("PRAGMA foreign_keys").fetchone()[
            0
        ]
        timeout = database.connection.execute("PRAGMA busy_timeout").fetchone()[0]
        assert journal.lower() == "wal"
        assert foreign_keys == 1
        assert timeout == 5000
    finally:
        database.close()
    reopened = open_database(str(path))
    try:
        assert reopened.members.get("missing") is None
    finally:
        reopened.close()


def test_two_in_memory_databases_are_isolated() -> None:
    first = open_database()
    second = open_database()
    try:
        from app.domain.entities import Member

        first.members.add(
            Member(id="m1", name="Ada", date_of_birth=date(1990, 1, 1))
        )
        assert second.members.get("m1") is None
        assert first.members.get("m1") is not None
    finally:
        first.close()
        second.close()


def test_round_trip_member_provider_plan_policy_catalogue(
    seeded_db: SqliteDatabase,
    member,
    provider,
    plan,
    policy,
    catalogue_entry,
) -> None:
    assert seeded_db.members.get("m1") == member
    assert seeded_db.providers.get("prov1") == provider
    assert seeded_db.plans.get("plan1", 2) == plan
    assert seeded_db.policies.get("pol1") == policy
    assert seeded_db.catalogue.get("PHYSIO-30") == catalogue_entry
    assert seeded_db.catalogue.as_mapping()["PHYSIO-30"] == catalogue_entry


def test_plan_versions_are_distinct(seeded_db: SqliteDatabase) -> None:
    later = Plan(
        id="plan1",
        version=3,
        deductible=Money(15_000),
        benefits=(
            Benefit(
                code="PHYSIO",
                name="Physiotherapy",
                covered=True,
                excluded=False,
                annual_limit_amount=None,
                annual_visit_limit=None,
            ),
        ),
    )
    seeded_db.plans.add(later)
    assert seeded_db.plans.get("plan1", 2) is not None
    assert seeded_db.plans.get("plan1", 2).deductible == Money(10_000)
    loaded = seeded_db.plans.get("plan1", 3)
    assert loaded == later
    assert loaded.benefits[0].annual_limit_amount is None


def test_round_trip_claim_and_lines(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim)
    stored = seeded_db.claims.get("claim1")
    assert stored is not None
    assert stored.claim == claim
    assert stored.rejected is False


def test_rejected_flag_is_a_fact_not_a_lifecycle_column(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    empty = Claim(
        id="claim-bad",
        member_id="m1",
        submitted_at=datetime(2026, 3, 20, 10, 0),
        lines=(),
    )
    seeded_db.claims.add(empty, rejected=True)
    stored = seeded_db.claims.get("claim-bad")
    assert stored is not None
    assert stored.rejected is True
    assert stored.claim.lines == ()
    assert not hasattr(stored.claim, "adjudication_state")


def test_round_trip_priced_line_decision(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim)
    amounts = DecisionAmounts(
        allowed=Money(4_000),
        above_allowed=Money(1_000),
        deductible_applied=Money(4_000),
        plan_paid=Money(0),
        denied_amount=Money(0),
    )
    trace = (
        TraceStep(
            step="annual_dollar_limit",
            rule="BENEFIT.PHYSIO.annual_limit_amount",
            plan_version=2,
            inputs={"after_deductible": 0, "limit_remaining": 100000},
            result="pass",
            accumulator_before=0,
            accumulator_after=0,
        ),
    )
    decision = _decision(
        amounts=amounts,
        reasons=(ReasonCodeId.MEM_DEDUCTIBLE,),
        trace=trace,
    )
    seeded_db.decisions.add(decision)
    loaded = seeded_db.decisions.get("dec1")
    assert loaded == decision


def test_round_trip_pre_pricing_decision_has_no_amounts(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim)
    decision = _decision(
        outcome=LineOutcome.NEEDS_REVIEW,
        amounts=None,
        reasons=(ReasonCodeId.REV_UNKNOWN_SERVICE,),
    )
    seeded_db.decisions.add(decision)
    loaded = seeded_db.decisions.get("dec1")
    assert loaded is not None
    assert loaded.amounts is None
    assert loaded.outcome is LineOutcome.NEEDS_REVIEW


def test_line_decision_sequences_append_and_current_is_highest(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim)
    first = _decision(
        decision_id="dec1",
        sequence=1,
        outcome=LineOutcome.NEEDS_REVIEW,
        reasons=(ReasonCodeId.REV_UNKNOWN_SERVICE,),
    )
    second = _decision(
        decision_id="dec2",
        sequence=2,
        outcome=LineOutcome.APPROVED,
        reasons=(ReasonCodeId.INFO_COVERED,),
        amounts=DecisionAmounts(
            allowed=Money(4_000),
            above_allowed=Money(1_000),
            deductible_applied=Money(0),
            plan_paid=Money(4_000),
            denied_amount=Money(0),
        ),
    )
    seeded_db.decisions.add(first)
    seeded_db.decisions.add(second)

    history = seeded_db.decisions.list_for_line("claim1-L1")
    assert [item.sequence for item in history] == [1, 2]
    assert history[0] == first
    current = seeded_db.decisions.current_for_line("claim1-L1")
    assert current == second
    assert seeded_db.decisions.get("dec1") == first


def test_duplicate_line_sequence_is_rejected(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim)
    seeded_db.decisions.add(_decision(decision_id="dec1", sequence=1))
    with pytest.raises(sqlite3.IntegrityError):
        seeded_db.decisions.add(_decision(decision_id="dec2", sequence=1))


def test_line_decisions_are_append_only(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim)
    seeded_db.decisions.add(_decision())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        seeded_db.connection.execute(
            "UPDATE line_decisions SET outcome = 'DENIED' WHERE id = 'dec1'"
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        seeded_db.connection.execute(
            "DELETE FROM line_decisions WHERE id = 'dec1'"
        )


def test_round_trip_accumulator_entry_and_reversal(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim)
    seeded_db.decisions.add(_decision())
    key = AccumulatorKey(
        member_id="m1",
        plan_year=2026,
        scope=AccumulatorScope.DEDUCTIBLE,
        benefit_code=None,
    )
    original = AccumulatorEntry(
        id="acc1",
        key=key,
        quantity=4_000,
        decision_id="dec1",
    )
    seeded_db.accumulators.add(original)
    assert seeded_db.accumulators.get("acc1") == original
    assert seeded_db.accumulators.balance(key) == 4_000

    seeded_db.decisions.add(_decision(decision_id="dec2", sequence=2))
    reversal = compensating_entry(original, id="acc1-rev", decision_id="dec2")
    seeded_db.accumulators.add(reversal)
    assert seeded_db.accumulators.get("acc1-rev") == reversal
    assert seeded_db.accumulators.balance(key) == 0
    assert seeded_db.accumulators.list_for_key(key) == (original, reversal)


def test_accumulator_entries_are_append_only(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim)
    seeded_db.decisions.add(_decision())
    seeded_db.accumulators.add(
        AccumulatorEntry(
            id="acc1",
            key=AccumulatorKey(
                member_id="m1",
                plan_year=2026,
                scope=AccumulatorScope.BENEFIT_VISITS,
                benefit_code="PHYSIO",
            ),
            quantity=1,
            decision_id="dec1",
        )
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        seeded_db.connection.execute(
            "UPDATE accumulator_entries SET quantity = 0 WHERE id = 'acc1'"
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        seeded_db.connection.execute(
            "DELETE FROM accumulator_entries WHERE id = 'acc1'"
        )


def test_round_trip_payment(seeded_db: SqliteDatabase, claim: Claim) -> None:
    seeded_db.claims.add(claim)
    payment = Payment(
        id="pay1",
        claim_id="claim1",
        amount=Money(4_000),
        paid_at=datetime(2026, 3, 22, 12, 0),
        reference="NEFT-1",
    )
    seeded_db.payments.add(payment)
    assert seeded_db.payments.list_for_claim("claim1") == (payment,)


def test_payment_check_rejects_non_positive_amount(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim)
    with pytest.raises(sqlite3.IntegrityError):
        seeded_db.connection.execute(
            """
            INSERT INTO payments (id, claim_id, amount_minor, paid_at, reference)
            VALUES ('pay0', 'claim1', 0, '2026-03-22T12:00:00', 'x')
            """
        )


def test_payments_are_append_only(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim)
    seeded_db.payments.add(
        Payment(
            id="pay1",
            claim_id="claim1",
            amount=Money(1),
            paid_at=datetime(2026, 3, 22, 12, 0),
            reference="NEFT-1",
        )
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        seeded_db.connection.execute(
            "UPDATE payments SET amount_minor = 2 WHERE id = 'pay1'"
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        seeded_db.connection.execute("DELETE FROM payments WHERE id = 'pay1'")


def test_round_trip_dispute_and_review_resolution(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim)
    first = _decision(
        outcome=LineOutcome.DENIED,
        reasons=(ReasonCodeId.DEN_EXCLUDED,),
    )
    seeded_db.decisions.add(first)
    dispute = Dispute(
        id="disp1",
        line_id="claim1-L1",
        disputed_decision_id="dec1",
        member_reason="This should be covered",
        state=DisputeState.OPEN,
    )
    seeded_db.disputes.add(dispute)
    assert seeded_db.disputes.get("disp1") == dispute
    assert seeded_db.disputes.list_open_for_line("claim1-L1") == (dispute,)

    second = _decision(
        decision_id="dec2",
        sequence=2,
        outcome=LineOutcome.DENIED,
        reasons=(ReasonCodeId.DEN_EXCLUDED,),
    )
    seeded_db.decisions.add(second)
    resolution = ReviewResolution(
        id="res1",
        line_id="claim1-L1",
        mode=ReviewResolutionMode.UPHOLD,
        reviewer_id="rev1",
        note="Denial stands",
        resulting_decision_id="dec2",
        dispute_id="disp1",
    )
    seeded_db.reviews.add(resolution)
    seeded_db.disputes.set_state("disp1", DisputeState.CLOSED)
    closed = seeded_db.disputes.get("disp1")
    assert closed is not None
    assert closed.state is DisputeState.CLOSED
    assert seeded_db.disputes.list_open_for_line("claim1-L1") == ()
    assert seeded_db.reviews.list_for_line("claim1-L1") == (resolution,)


def test_round_trip_review_resolution_with_corrections(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim)
    seeded_db.decisions.add(
        _decision(
            outcome=LineOutcome.NEEDS_REVIEW,
            reasons=(ReasonCodeId.REV_UNKNOWN_SERVICE,),
        )
    )
    seeded_db.decisions.add(
        _decision(
            decision_id="dec2",
            sequence=2,
            reasons=(ReasonCodeId.INFO_COVERED,),
        )
    )
    corrections = LineFactCorrections(
        service_code="PHYSIO-60",
        billed_amount=Money(6_000),
    )
    resolution = ReviewResolution(
        id="res1",
        line_id="claim1-L1",
        mode=ReviewResolutionMode.CORRECT_FACTS,
        reviewer_id="rev1",
        note="Corrected service code",
        resulting_decision_id="dec2",
        corrections=corrections,
    )
    seeded_db.reviews.add(resolution)
    loaded = seeded_db.reviews.list_for_line("claim1-L1")[0]
    assert loaded == resolution


def test_fact_correction_updates_current_line_not_prior_decision(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim)
    original = _decision(
        outcome=LineOutcome.NEEDS_REVIEW,
        reasons=(ReasonCodeId.REV_UNKNOWN_SERVICE,),
        trace=(
            TraceStep(
                step="service_catalogue",
                rule="CATALOGUE.service_code",
                plan_version=2,
                inputs={"service_code": "PHYSIO-30"},
                result="unknown",
            ),
        ),
    )
    seeded_db.decisions.add(original)
    seeded_db.claims.update_line_facts(
        "claim1-L1",
        LineFactCorrections(service_code="PHYSIO-60"),
    )
    stored = seeded_db.claims.get("claim1")
    assert stored is not None
    assert stored.claim.lines[0].service_code == "PHYSIO-60"
    assert seeded_db.decisions.get("dec1") == original


def test_foreign_key_rejects_claim_without_member(
    db: SqliteDatabase, claim: Claim
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.claims.add(claim)


def test_ledger_entry_requires_existing_decision(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim)
    with pytest.raises(sqlite3.IntegrityError):
        seeded_db.accumulators.add(
            AccumulatorEntry(
                id="orphan",
                key=AccumulatorKey(
                    member_id="m1",
                    plan_year=2026,
                    scope=AccumulatorScope.DEDUCTIBLE,
                    benefit_code=None,
                ),
                quantity=1,
                decision_id="missing-decision",
            )
        )


def test_catalogue_allows_unpriced_service(seeded_db: SqliteDatabase) -> None:
    entry = ServiceCatalogueEntry(
        service_code="XRAY-1",
        description="X-ray",
        benefit_code="DIAG",
        scheduled_amount=None,
    )
    seeded_db.catalogue.add(entry)
    assert seeded_db.catalogue.get("XRAY-1") == entry


def test_duplicate_line_number_on_same_claim_is_rejected(
    seeded_db: SqliteDatabase,
) -> None:
    line = ClaimLine(
        id="claim1-L1",
        claim_id="claim1",
        line_number=1,
        provider_id="prov1",
        service_code="PHYSIO-30",
        service_date=date(2026, 3, 15),
        billed_amount=Money(5_000),
        diagnosis_code="M54.5",
    )
    claim = Claim(
        id="claim1",
        member_id="m1",
        submitted_at=datetime(2026, 3, 20, 10, 0),
        lines=(line,),
    )
    seeded_db.claims.add(claim)
    with pytest.raises(sqlite3.IntegrityError):
        seeded_db.connection.execute(
            """
            INSERT INTO claim_lines (
                id, claim_id, line_number, provider_id, service_code,
                service_date, billed_amount_minor, diagnosis_code
            ) VALUES (
                'claim1-L2', 'claim1', 1, 'prov1', 'PHYSIO-30',
                '2026-03-16', 5000, 'M54.5'
            )
            """
        )


def _two_line_claim(seeded_db: SqliteDatabase) -> tuple[str, str]:
    """Persist a claim with two lines; return their line ids."""
    line1 = ClaimLine(
        id="claim2-L1",
        claim_id="claim2",
        line_number=1,
        provider_id="prov1",
        service_code="PHYSIO-30",
        service_date=date(2026, 3, 15),
        billed_amount=Money(5_000),
        diagnosis_code="M54.5",
    )
    line2 = ClaimLine(
        id="claim2-L2",
        claim_id="claim2",
        line_number=2,
        provider_id="prov1",
        service_code="PHYSIO-30",
        service_date=date(2026, 3, 16),
        billed_amount=Money(5_000),
        diagnosis_code="M54.5",
    )
    seeded_db.claims.add(
        Claim(
            id="claim2",
            member_id="m1",
            submitted_at=datetime(2026, 3, 20, 10, 0),
            lines=(line1, line2),
        )
    )
    return line1.id, line2.id


def test_policy_rejects_nonexistent_plan_id(seeded_db: SqliteDatabase) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="existing plan"):
        seeded_db.policies.add(
            Policy(
                id="pol-bad",
                member_id="m1",
                plan_id="missing-plan",
                effective_date=date(2026, 1, 1),
                termination_date=None,
            )
        )


def test_claims_rejected_flag_is_immutable(
    seeded_db: SqliteDatabase, claim: Claim
) -> None:
    seeded_db.claims.add(claim, rejected=True)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        seeded_db.connection.execute(
            "UPDATE claims SET rejected = 0 WHERE id = ?",
            (claim.id,),
        )
    stored = seeded_db.claims.get(claim.id)
    assert stored is not None
    assert stored.rejected is True


def test_dispute_rejects_decision_on_different_line(
    seeded_db: SqliteDatabase,
) -> None:
    line1_id, line2_id = _two_line_claim(seeded_db)
    seeded_db.decisions.add(
        _decision(decision_id="dec-line2", line_id=line2_id)
    )
    with pytest.raises(sqlite3.IntegrityError, match="dispute line"):
        seeded_db.disputes.add(
            Dispute(
                id="disp-cross",
                line_id=line1_id,
                disputed_decision_id="dec-line2",
                member_reason="wrong line",
                state=DisputeState.OPEN,
            )
        )


def test_dispute_rejects_repoint_to_decision_on_different_line(
    seeded_db: SqliteDatabase,
) -> None:
    line1_id, line2_id = _two_line_claim(seeded_db)
    seeded_db.decisions.add(_decision(decision_id="dec-line1", line_id=line1_id))
    seeded_db.decisions.add(
        _decision(decision_id="dec-line2", line_id=line2_id)
    )
    seeded_db.disputes.add(
        Dispute(
            id="disp1",
            line_id=line1_id,
            disputed_decision_id="dec-line1",
            member_reason="appeal",
            state=DisputeState.OPEN,
        )
    )
    with pytest.raises(sqlite3.IntegrityError, match="dispute line"):
        seeded_db.connection.execute(
            "UPDATE disputes SET disputed_decision_id = ? WHERE id = ?",
            ("dec-line2", "disp1"),
        )


def test_review_resolution_rejects_resulting_decision_on_different_line(
    seeded_db: SqliteDatabase,
) -> None:
    line1_id, line2_id = _two_line_claim(seeded_db)
    seeded_db.decisions.add(
        _decision(decision_id="dec-line2", line_id=line2_id)
    )
    with pytest.raises(sqlite3.IntegrityError, match="resolution line"):
        seeded_db.reviews.add(
            ReviewResolution(
                id="res-cross",
                line_id=line1_id,
                mode=ReviewResolutionMode.CORRECT_FACTS,
                reviewer_id="rev1",
                note="bad pointer",
                resulting_decision_id="dec-line2",
                corrections=LineFactCorrections(service_code="PHYSIO-60"),
            )
        )


def test_review_resolution_rejects_dispute_on_different_line(
    seeded_db: SqliteDatabase,
) -> None:
    line1_id, line2_id = _two_line_claim(seeded_db)
    seeded_db.decisions.add(_decision(decision_id="dec-line2", line_id=line2_id))
    seeded_db.disputes.add(
        Dispute(
            id="disp-line2",
            line_id=line2_id,
            disputed_decision_id="dec-line2",
            member_reason="appeal",
            state=DisputeState.OPEN,
        )
    )
    seeded_db.decisions.add(_decision(decision_id="dec-line1", line_id=line1_id))
    with pytest.raises(sqlite3.IntegrityError, match="resolution line"):
        seeded_db.reviews.add(
            ReviewResolution(
                id="res-cross-dispute",
                line_id=line1_id,
                mode=ReviewResolutionMode.UPHOLD,
                reviewer_id="rev1",
                note="wrong dispute",
                resulting_decision_id="dec-line1",
                dispute_id="disp-line2",
            )
        )


def test_domain_modules_do_not_import_sqlite_or_infrastructure() -> None:
    domain_dir = Path("app/domain")
    for path in domain_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "sqlite3"
                    assert not alias.name.startswith("app.infrastructure")
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module != "sqlite3"
                assert not module.startswith("app.infrastructure")
