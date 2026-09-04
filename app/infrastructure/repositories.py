"""Thin SQLite repositories. Persistence only — no adjudication rules."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from app.domain.accumulators import AccumulatorEntry, AccumulatorKey
from app.domain.entities import (
    Claim,
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
)
from app.domain.states import DisputeState
from app.infrastructure.mapping import (
    accumulator_entry_from_row,
    amounts_to_columns,
    catalogue_entry_from_row,
    claim_from_rows,
    dispute_from_row,
    int_from_bool,
    line_decision_from_row,
    member_from_row,
    payment_from_row,
    plan_from_rows,
    policy_from_row,
    provider_from_row,
    reasons_to_json,
    review_resolution_from_row,
    trace_to_json,
)


@dataclass(frozen=True, slots=True)
class StoredClaim:
    """Claim envelope plus the gate-0 structural-invalidity fact."""

    claim: Claim
    rejected: bool


class MemberRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, member: Member) -> None:
        self._conn.execute(
            "INSERT INTO members (id, name, date_of_birth) VALUES (?, ?, ?)",
            (member.id, member.name, member.date_of_birth.isoformat()),
        )

    def get(self, member_id: str) -> Member | None:
        row = self._conn.execute(
            "SELECT * FROM members WHERE id = ?", (member_id,)
        ).fetchone()
        return member_from_row(row) if row else None


class ProviderRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, provider: Provider) -> None:
        self._conn.execute(
            "INSERT INTO providers (id, name) VALUES (?, ?)",
            (provider.id, provider.name),
        )

    def get(self, provider_id: str) -> Provider | None:
        row = self._conn.execute(
            "SELECT * FROM providers WHERE id = ?", (provider_id,)
        ).fetchone()
        return provider_from_row(row) if row else None


class PlanRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, plan: Plan) -> None:
        self._conn.execute(
            "INSERT INTO plans (id, version, deductible_minor) VALUES (?, ?, ?)",
            (plan.id, plan.version, plan.deductible.minor_units),
        )
        self._conn.executemany(
            """
            INSERT INTO benefits (
                plan_id, plan_version, code, name, covered, excluded,
                annual_limit_amount_minor, annual_visit_limit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    plan.id,
                    plan.version,
                    benefit.code,
                    benefit.name,
                    int_from_bool(benefit.covered),
                    int_from_bool(benefit.excluded),
                    (
                        None
                        if benefit.annual_limit_amount is None
                        else benefit.annual_limit_amount.minor_units
                    ),
                    benefit.annual_visit_limit,
                )
                for benefit in plan.benefits
            ],
        )

    def get(self, plan_id: str, version: int) -> Plan | None:
        plan_row = self._conn.execute(
            "SELECT * FROM plans WHERE id = ? AND version = ?",
            (plan_id, version),
        ).fetchone()
        if plan_row is None:
            return None
        benefit_rows = self._conn.execute(
            """
            SELECT * FROM benefits
            WHERE plan_id = ? AND plan_version = ?
            ORDER BY code
            """,
            (plan_id, version),
        ).fetchall()
        return plan_from_rows(plan_row, benefit_rows)

    def get_latest(self, plan_id: str) -> Plan | None:
        row = self._conn.execute(
            """
            SELECT version FROM plans
            WHERE id = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (plan_id,),
        ).fetchone()
        if row is None:
            return None
        return self.get(plan_id, int(row["version"]))


class PolicyRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, policy: Policy) -> None:
        termination = (
            None
            if policy.termination_date is None
            else policy.termination_date.isoformat()
        )
        self._conn.execute(
            """
            INSERT INTO policies (
                id, member_id, plan_id, effective_date, termination_date
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                policy.id,
                policy.member_id,
                policy.plan_id,
                policy.effective_date.isoformat(),
                termination,
            ),
        )

    def get(self, policy_id: str) -> Policy | None:
        row = self._conn.execute(
            "SELECT * FROM policies WHERE id = ?", (policy_id,)
        ).fetchone()
        return policy_from_row(row) if row else None

    def list_for_member(self, member_id: str) -> tuple[Policy, ...]:
        rows = self._conn.execute(
            """
            SELECT * FROM policies
            WHERE member_id = ?
            ORDER BY effective_date
            """,
            (member_id,),
        ).fetchall()
        return tuple(policy_from_row(row) for row in rows)


class ServiceCatalogueRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, entry: ServiceCatalogueEntry) -> None:
        scheduled = (
            None
            if entry.scheduled_amount is None
            else entry.scheduled_amount.minor_units
        )
        self._conn.execute(
            """
            INSERT INTO service_catalogue (
                service_code, description, benefit_code, scheduled_amount_minor
            ) VALUES (?, ?, ?, ?)
            """,
            (entry.service_code, entry.description, entry.benefit_code, scheduled),
        )

    def get(self, service_code: str) -> ServiceCatalogueEntry | None:
        row = self._conn.execute(
            "SELECT * FROM service_catalogue WHERE service_code = ?",
            (service_code,),
        ).fetchone()
        return catalogue_entry_from_row(row) if row else None

    def as_mapping(self) -> dict[str, ServiceCatalogueEntry]:
        rows = self._conn.execute("SELECT * FROM service_catalogue").fetchall()
        return {row["service_code"]: catalogue_entry_from_row(row) for row in rows}


class ClaimRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, claim: Claim, *, rejected: bool = False) -> None:
        self._conn.execute(
            """
            INSERT INTO claims (id, member_id, submitted_at, rejected)
            VALUES (?, ?, ?, ?)
            """,
            (
                claim.id,
                claim.member_id,
                claim.submitted_at.isoformat(),
                int_from_bool(rejected),
            ),
        )
        self._conn.executemany(
            """
            INSERT INTO claim_lines (
                id, claim_id, line_number, provider_id, service_code,
                service_date, billed_amount_minor, diagnosis_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    line.id,
                    line.claim_id,
                    line.line_number,
                    line.provider_id,
                    line.service_code,
                    line.service_date.isoformat(),
                    line.billed_amount.minor_units,
                    line.diagnosis_code,
                )
                for line in claim.lines
            ],
        )

    def get(self, claim_id: str) -> StoredClaim | None:
        claim_row = self._conn.execute(
            "SELECT * FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        if claim_row is None:
            return None
        line_rows = self._conn.execute(
            """
            SELECT * FROM claim_lines
            WHERE claim_id = ?
            ORDER BY line_number
            """,
            (claim_id,),
        ).fetchall()
        return StoredClaim(
            claim=claim_from_rows(claim_row, line_rows),
            rejected=bool(claim_row["rejected"]),
        )

    def list_for_member(self, member_id: str) -> tuple[StoredClaim, ...]:
        claim_rows = self._conn.execute(
            """
            SELECT * FROM claims
            WHERE member_id = ?
            ORDER BY submitted_at
            """,
            (member_id,),
        ).fetchall()
        stored: list[StoredClaim] = []
        for row in claim_rows:
            record = self.get(row["id"])
            if record is not None:
                stored.append(record)
        return tuple(stored)

    def update_line_facts(
        self, line_id: str, corrections: LineFactCorrections
    ) -> None:
        assignments: list[str] = []
        params: list[object] = []
        if corrections.service_code is not None:
            assignments.append("service_code = ?")
            params.append(corrections.service_code)
        if corrections.service_date is not None:
            assignments.append("service_date = ?")
            params.append(corrections.service_date.isoformat())
        if corrections.provider_id is not None:
            assignments.append("provider_id = ?")
            params.append(corrections.provider_id)
        if corrections.billed_amount is not None:
            assignments.append("billed_amount_minor = ?")
            params.append(corrections.billed_amount.minor_units)
        if corrections.diagnosis_code is not None:
            assignments.append("diagnosis_code = ?")
            params.append(corrections.diagnosis_code)
        params.append(line_id)
        cursor = self._conn.execute(
            f"UPDATE claim_lines SET {', '.join(assignments)} WHERE id = ?",
            params,
        )
        if cursor.rowcount != 1:
            raise ValueError(f"claim line not found: {line_id}")


class LineDecisionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, decision: LineDecision) -> None:
        amounts = amounts_to_columns(decision.amounts)
        self._conn.execute(
            """
            INSERT INTO line_decisions (
                id, line_id, sequence, source, outcome,
                allowed_minor, above_allowed_minor, deductible_applied_minor,
                plan_paid_minor, denied_amount_minor,
                reasons_json, trace_json, plan_version, decided_at, decided_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.id,
                decision.line_id,
                decision.sequence,
                decision.source.value,
                decision.outcome.value,
                *amounts,
                reasons_to_json(decision.reasons),
                trace_to_json(decision.trace),
                decision.plan_version,
                decision.decided_at.isoformat(),
                decision.decided_by,
            ),
        )

    def get(self, decision_id: str) -> LineDecision | None:
        row = self._conn.execute(
            "SELECT * FROM line_decisions WHERE id = ?", (decision_id,)
        ).fetchone()
        return line_decision_from_row(row) if row else None

    def list_for_line(self, line_id: str) -> tuple[LineDecision, ...]:
        rows = self._conn.execute(
            """
            SELECT * FROM line_decisions
            WHERE line_id = ?
            ORDER BY sequence
            """,
            (line_id,),
        ).fetchall()
        return tuple(line_decision_from_row(row) for row in rows)

    def current_for_line(self, line_id: str) -> LineDecision | None:
        row = self._conn.execute(
            """
            SELECT * FROM line_decisions
            WHERE line_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (line_id,),
        ).fetchone()
        return line_decision_from_row(row) if row else None

    def list_for_claim(self, claim_id: str) -> tuple[LineDecision, ...]:
        rows = self._conn.execute(
            """
            SELECT d.* FROM line_decisions d
            JOIN claim_lines l ON l.id = d.line_id
            WHERE l.claim_id = ?
            ORDER BY l.line_number, d.sequence
            """,
            (claim_id,),
        ).fetchall()
        return tuple(line_decision_from_row(row) for row in rows)


class AccumulatorRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, entry: AccumulatorEntry) -> None:
        self._conn.execute(
            """
            INSERT INTO accumulator_entries (
                id, member_id, plan_year, scope, benefit_code,
                quantity, decision_id, reverses_entry_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.id,
                entry.key.member_id,
                entry.key.plan_year,
                entry.key.scope.value,
                entry.key.benefit_code,
                entry.quantity,
                entry.decision_id,
                entry.reverses_entry_id,
            ),
        )

    def get(self, entry_id: str) -> AccumulatorEntry | None:
        row = self._conn.execute(
            "SELECT * FROM accumulator_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return accumulator_entry_from_row(row) if row else None

    def list_for_key(self, key: AccumulatorKey) -> tuple[AccumulatorEntry, ...]:
        if key.benefit_code is None:
            rows = self._conn.execute(
                """
                SELECT * FROM accumulator_entries
                WHERE member_id = ? AND plan_year = ? AND scope = ?
                  AND benefit_code IS NULL
                """,
                (key.member_id, key.plan_year, key.scope.value),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM accumulator_entries
                WHERE member_id = ? AND plan_year = ? AND scope = ?
                  AND benefit_code = ?
                """,
                (key.member_id, key.plan_year, key.scope.value, key.benefit_code),
            ).fetchall()
        return tuple(accumulator_entry_from_row(row) for row in rows)

    def balance(self, key: AccumulatorKey) -> int:
        if key.benefit_code is None:
            row = self._conn.execute(
                """
                SELECT COALESCE(SUM(quantity), 0) AS total
                FROM accumulator_entries
                WHERE member_id = ? AND plan_year = ? AND scope = ?
                  AND benefit_code IS NULL
                """,
                (key.member_id, key.plan_year, key.scope.value),
            ).fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT COALESCE(SUM(quantity), 0) AS total
                FROM accumulator_entries
                WHERE member_id = ? AND plan_year = ? AND scope = ?
                  AND benefit_code = ?
                """,
                (key.member_id, key.plan_year, key.scope.value, key.benefit_code),
            ).fetchone()
        return int(row["total"])


class PaymentRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, payment: Payment) -> None:
        self._conn.execute(
            """
            INSERT INTO payments (id, claim_id, amount_minor, paid_at, reference)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payment.id,
                payment.claim_id,
                payment.amount.minor_units,
                payment.paid_at.isoformat(),
                payment.reference,
            ),
        )

    def list_for_claim(self, claim_id: str) -> tuple[Payment, ...]:
        rows = self._conn.execute(
            """
            SELECT * FROM payments
            WHERE claim_id = ?
            ORDER BY paid_at
            """,
            (claim_id,),
        ).fetchall()
        return tuple(payment_from_row(row) for row in rows)


class DisputeRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, dispute: Dispute) -> None:
        self._conn.execute(
            """
            INSERT INTO disputes (
                id, line_id, disputed_decision_id, member_reason, state
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                dispute.id,
                dispute.line_id,
                dispute.disputed_decision_id,
                dispute.member_reason,
                dispute.state.value,
            ),
        )

    def get(self, dispute_id: str) -> Dispute | None:
        row = self._conn.execute(
            "SELECT * FROM disputes WHERE id = ?", (dispute_id,)
        ).fetchone()
        return dispute_from_row(row) if row else None

    def list_for_line(self, line_id: str) -> tuple[Dispute, ...]:
        rows = self._conn.execute(
            "SELECT * FROM disputes WHERE line_id = ?", (line_id,)
        ).fetchall()
        return tuple(dispute_from_row(row) for row in rows)

    def list_open_for_line(self, line_id: str) -> tuple[Dispute, ...]:
        rows = self._conn.execute(
            "SELECT * FROM disputes WHERE line_id = ? AND state = ?",
            (line_id, DisputeState.OPEN.value),
        ).fetchall()
        return tuple(dispute_from_row(row) for row in rows)

    def set_state(self, dispute_id: str, state: DisputeState) -> None:
        cursor = self._conn.execute(
            "UPDATE disputes SET state = ? WHERE id = ?",
            (state.value, dispute_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"dispute not found: {dispute_id}")


class ReviewResolutionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def add(self, resolution: ReviewResolution) -> None:
        corrections = resolution.corrections
        self._conn.execute(
            """
            INSERT INTO review_resolutions (
                id, line_id, dispute_id, mode, reviewer_id, note,
                resulting_decision_id,
                correction_service_code, correction_service_date,
                correction_provider_id, correction_billed_amount_minor,
                correction_diagnosis_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolution.id,
                resolution.line_id,
                resolution.dispute_id,
                resolution.mode.value,
                resolution.reviewer_id,
                resolution.note,
                resolution.resulting_decision_id,
                None if corrections is None else corrections.service_code,
                (
                    None
                    if corrections is None or corrections.service_date is None
                    else corrections.service_date.isoformat()
                ),
                None if corrections is None else corrections.provider_id,
                (
                    None
                    if corrections is None or corrections.billed_amount is None
                    else corrections.billed_amount.minor_units
                ),
                None if corrections is None else corrections.diagnosis_code,
            ),
        )

    def list_for_line(self, line_id: str) -> tuple[ReviewResolution, ...]:
        rows = self._conn.execute(
            "SELECT * FROM review_resolutions WHERE line_id = ? ORDER BY rowid",
            (line_id,),
        ).fetchall()
        return tuple(review_resolution_from_row(row) for row in rows)
