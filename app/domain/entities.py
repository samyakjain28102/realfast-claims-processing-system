"""Domain entities — facts on claims/lines; computed outcomes on decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.domain.money import Money
from app.domain.reasons import ReasonCodeId
from app.domain.rules import Benefit
from app.domain.states import (
    DecisionSource,
    DisputeState,
    LineOutcome,
    ReviewResolutionMode,
)


@dataclass(frozen=True, slots=True)
class Member:
    """Identity only — no clinical data."""

    id: str
    name: str
    date_of_birth: date

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not self.name:
            raise ValueError("name must be non-empty")


@dataclass(frozen=True, slots=True)
class Provider:
    id: str
    name: str

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not self.name:
            raise ValueError("name must be non-empty")


@dataclass(frozen=True, slots=True)
class Plan:
    id: str
    version: int
    deductible: Money
    benefits: tuple[Benefit, ...]

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if self.version < 1:
            raise ValueError("version must be at least 1")


@dataclass(frozen=True, slots=True)
class Policy:
    """Membership dates only — deductible lives on Plan (D26)."""

    id: str
    member_id: str
    plan_id: str
    effective_date: date
    termination_date: date | None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not self.member_id:
            raise ValueError("member_id must be non-empty")
        if not self.plan_id:
            raise ValueError("plan_id must be non-empty")
        if self.termination_date is not None and self.termination_date < self.effective_date:
            raise ValueError("termination_date must not precede effective_date")


@dataclass(frozen=True, slots=True)
class ServiceCatalogueEntry:
    service_code: str
    description: str
    benefit_code: str
    scheduled_amount: Money | None

    def __post_init__(self) -> None:
        if not self.service_code:
            raise ValueError("service_code must be non-empty")
        if not self.benefit_code:
            raise ValueError("benefit_code must be non-empty")


@dataclass(frozen=True, slots=True)
class ClaimLine:
    """Submitted facts for one service occurrence — clinical data lives here."""

    id: str
    claim_id: str
    line_number: int
    provider_id: str
    service_code: str
    service_date: date
    billed_amount: Money
    diagnosis_code: str

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not self.claim_id:
            raise ValueError("claim_id must be non-empty")
        if self.line_number < 1:
            raise ValueError("line_number must be at least 1")
        if not self.provider_id:
            raise ValueError("provider_id must be non-empty")
        if not self.service_code:
            raise ValueError("service_code must be non-empty")
        if not self.diagnosis_code:
            raise ValueError("diagnosis_code must be non-empty")


@dataclass(frozen=True, slots=True)
class Claim:
    """Claim envelope — adjudication and settlement states are derived, not stored."""

    id: str
    member_id: str
    submitted_at: datetime
    lines: tuple[ClaimLine, ...]

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not self.member_id:
            raise ValueError("member_id must be non-empty")
        line_numbers = [line.line_number for line in self.lines]
        if len(line_numbers) != len(set(line_numbers)):
            raise ValueError("line_number must be unique within a claim")


@dataclass(frozen=True, slots=True)
class DecisionAmounts:
    """Financial breakdown when a decision reached pricing (D27)."""

    allowed: Money
    above_allowed: Money
    deductible_applied: Money
    plan_paid: Money
    denied_amount: Money

    def check_conservation(self, billed: Money) -> None:
        """Verify money conservation: billed splits across all parties."""
        total = (
            self.above_allowed
            + self.deductible_applied
            + self.plan_paid
            + self.denied_amount
        )
        if total != billed:
            raise ValueError(
                "money conservation violated: "
                f"billed={billed.minor_units}, assigned={total.minor_units}"
            )


@dataclass(frozen=True, slots=True)
class TraceStep:
    """One gate evaluation recorded on a line decision."""

    step: str
    rule: str
    plan_version: int
    inputs: dict[str, Any]
    result: str
    accumulator_before: int | None = None
    accumulator_after: int | None = None


@dataclass(frozen=True, slots=True)
class LineDecision:
    """Append-only adjudication outcome for a line."""

    id: str
    line_id: str
    sequence: int
    source: DecisionSource
    outcome: LineOutcome
    reasons: tuple[ReasonCodeId, ...]
    trace: tuple[TraceStep, ...]
    plan_version: int
    decided_at: datetime
    decided_by: str
    amounts: DecisionAmounts | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not self.line_id:
            raise ValueError("line_id must be non-empty")
        if self.sequence < 1:
            raise ValueError("sequence must be at least 1")
        if self.plan_version < 1:
            raise ValueError("plan_version must be at least 1")
        if not self.decided_by:
            raise ValueError("decided_by must be non-empty")
        if not self.reasons:
            raise ValueError("reasons must not be empty")


@dataclass(frozen=True, slots=True)
class Payment:
    """Append-only record that money moved — never negative."""

    id: str
    claim_id: str
    amount: Money
    paid_at: datetime
    reference: str

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not self.claim_id:
            raise ValueError("claim_id must be non-empty")
        if self.amount.minor_units <= 0:
            raise ValueError("payment amount must be positive")
        if not self.reference:
            raise ValueError("reference must be non-empty")


@dataclass(frozen=True, slots=True)
class Dispute:
    """Appeal against a specific line decision — original decision stays immutable."""

    id: str
    line_id: str
    disputed_decision_id: str
    member_reason: str
    state: DisputeState

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not self.line_id:
            raise ValueError("line_id must be non-empty")
        if not self.disputed_decision_id:
            raise ValueError("disputed_decision_id must be non-empty")
        if not self.member_reason:
            raise ValueError("member_reason must be non-empty")


@dataclass(frozen=True, slots=True)
class LineFactCorrections:
    """Correctable claim facts for review resolution (D7)."""

    service_code: str | None = None
    service_date: date | None = None
    provider_id: str | None = None
    billed_amount: Money | None = None
    diagnosis_code: str | None = None

    def __post_init__(self) -> None:
        if not any(
            (
                self.service_code is not None,
                self.service_date is not None,
                self.provider_id is not None,
                self.billed_amount is not None,
                self.diagnosis_code is not None,
            )
        ):
            raise ValueError("at least one correction field must be set")


@dataclass(frozen=True, slots=True)
class ReviewResolution:
    """Exit from NEEDS_REVIEW or UNDER_APPEAL — uphold recorded here, not on LineDecision (D29)."""

    id: str
    line_id: str
    mode: ReviewResolutionMode
    reviewer_id: str
    note: str
    resulting_decision_id: str
    dispute_id: str | None = None
    corrections: LineFactCorrections | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not self.line_id:
            raise ValueError("line_id must be non-empty")
        if not self.reviewer_id:
            raise ValueError("reviewer_id must be non-empty")
        if not self.note:
            raise ValueError("note must be non-empty")
        if not self.resulting_decision_id:
            raise ValueError("resulting_decision_id must be non-empty")
        if self.mode is ReviewResolutionMode.CORRECT_FACTS and self.corrections is None:
            raise ValueError("correct_facts resolution requires corrections")
        if self.mode is ReviewResolutionMode.UPHOLD and self.corrections is not None:
            raise ValueError("uphold resolution must not include corrections")
