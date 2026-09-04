"""Application read models — not domain entities, not HTTP schemas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ReasonView:
    code: str
    message: str
    appealable: bool | None


@dataclass(frozen=True, slots=True)
class AmountBreakdownView:
    allowed_minor: int
    above_allowed_minor: int
    deductible_applied_minor: int
    plan_paid_minor: int
    denied_amount_minor: int


@dataclass(frozen=True, slots=True)
class TraceStepView:
    step: str
    rule: str
    plan_version: int
    inputs: dict[str, Any]
    result: str
    accumulator_before: int | None
    accumulator_after: int | None


@dataclass(frozen=True, slots=True)
class LineDecisionView:
    id: str
    sequence: int
    source: str
    outcome: str
    reasons: tuple[ReasonView, ...]
    trace: tuple[TraceStepView, ...]
    plan_version: int
    decided_at: datetime
    amounts: AmountBreakdownView | None


@dataclass(frozen=True, slots=True)
class ClaimLineView:
    id: str
    line_number: int
    provider_id: str
    service_code: str
    service_date: date
    billed_amount_minor: int
    line_state: str
    decision: LineDecisionView | None


@dataclass(frozen=True, slots=True)
class ClaimView:
    id: str
    member_id: str
    submitted_at: datetime
    rejected: bool
    rejection_reason: str | None
    adjudication_state: str
    settlement_state: str
    payable_minor: int
    lines: tuple[ClaimLineView, ...]


@dataclass(frozen=True, slots=True)
class ClaimSummaryView:
    id: str
    member_id: str
    submitted_at: datetime
    rejected: bool
    adjudication_state: str
    settlement_state: str
    payable_minor: int


@dataclass(frozen=True, slots=True)
class AccumulatorBalanceView:
    plan_year: int
    scope: str
    benefit_code: str | None
    consumed: int
    limit_minor: int | None
    limit_visits: int | None


@dataclass(frozen=True, slots=True)
class MemberAccumulatorsView:
    member_id: str
    balances: tuple[AccumulatorBalanceView, ...]


@dataclass(frozen=True, slots=True)
class EobPaymentView:
    id: str
    amount_minor: int
    paid_at: datetime
    reference: str


@dataclass(frozen=True, slots=True)
class EobLineView:
    line_number: int
    service_code: str
    service_date: date
    billed_minor: int
    line_state: str
    outcome: str | None
    explanations: tuple[ReasonView, ...]
    amounts: AmountBreakdownView | None


@dataclass(frozen=True, slots=True)
class EobView:
    """Member-facing summary assembled from current decisions and payments."""

    claim_id: str
    member_id: str
    adjudication_state: str
    settlement_state: str
    billed_minor: int
    payable_minor: int
    paid_minor: int
    member_responsibility_minor: int
    lines: tuple[EobLineView, ...]
    payments: tuple[EobPaymentView, ...]
