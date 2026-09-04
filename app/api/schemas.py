"""Pydantic request and response models — HTTP boundary only."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.application.read_models import (
    AccumulatorBalanceView,
    AmountBreakdownView,
    ClaimLineView,
    ClaimSummaryView,
    ClaimView,
    LineDecisionView,
    MemberAccumulatorsView,
    ReasonView,
    TraceStepView,
)


class SubmitClaimLineRequest(BaseModel):
    line_number: int = Field(ge=1)
    provider_id: str
    service_code: str
    service_date: date
    billed_amount_minor: int = Field(ge=0)
    diagnosis_code: str


class SubmitClaimRequest(BaseModel):
    id: str
    member_id: str
    submitted_at: datetime
    lines: tuple[SubmitClaimLineRequest, ...]


class ReasonResponse(BaseModel):
    code: str
    message: str
    appealable: bool | None

    @classmethod
    def from_view(cls, view: ReasonView) -> ReasonResponse:
        return cls(
            code=view.code,
            message=view.message,
            appealable=view.appealable,
        )


class TraceStepResponse(BaseModel):
    step: str
    rule: str
    plan_version: int
    inputs: dict[str, Any]
    result: str
    accumulator_before: int | None
    accumulator_after: int | None

    @classmethod
    def from_view(cls, view: TraceStepView) -> TraceStepResponse:
        return cls(
            step=view.step,
            rule=view.rule,
            plan_version=view.plan_version,
            inputs=view.inputs,
            result=view.result,
            accumulator_before=view.accumulator_before,
            accumulator_after=view.accumulator_after,
        )


class AmountBreakdownResponse(BaseModel):
    allowed_minor: int
    above_allowed_minor: int
    deductible_applied_minor: int
    plan_paid_minor: int
    denied_amount_minor: int

    @classmethod
    def from_view(cls, view: AmountBreakdownView) -> AmountBreakdownResponse:
        return cls(
            allowed_minor=view.allowed_minor,
            above_allowed_minor=view.above_allowed_minor,
            deductible_applied_minor=view.deductible_applied_minor,
            plan_paid_minor=view.plan_paid_minor,
            denied_amount_minor=view.denied_amount_minor,
        )


class LineDecisionResponse(BaseModel):
    id: str
    sequence: int
    source: str
    outcome: str
    reasons: tuple[ReasonResponse, ...]
    trace: tuple[TraceStepResponse, ...]
    plan_version: int
    decided_at: datetime
    amounts: AmountBreakdownResponse | None

    @classmethod
    def from_view(cls, view: LineDecisionView) -> LineDecisionResponse:
        return cls(
            id=view.id,
            sequence=view.sequence,
            source=view.source,
            outcome=view.outcome,
            reasons=tuple(ReasonResponse.from_view(r) for r in view.reasons),
            trace=tuple(TraceStepResponse.from_view(t) for t in view.trace),
            plan_version=view.plan_version,
            decided_at=view.decided_at,
            amounts=(
                AmountBreakdownResponse.from_view(view.amounts)
                if view.amounts is not None
                else None
            ),
        )


class ClaimLineResponse(BaseModel):
    id: str
    line_number: int
    provider_id: str
    service_code: str
    service_date: date
    billed_amount_minor: int
    line_state: str
    decision: LineDecisionResponse | None

    @classmethod
    def from_view(cls, view: ClaimLineView) -> ClaimLineResponse:
        return cls(
            id=view.id,
            line_number=view.line_number,
            provider_id=view.provider_id,
            service_code=view.service_code,
            service_date=view.service_date,
            billed_amount_minor=view.billed_amount_minor,
            line_state=view.line_state,
            decision=(
                LineDecisionResponse.from_view(view.decision)
                if view.decision is not None
                else None
            ),
        )


class ClaimResponse(BaseModel):
    id: str
    member_id: str
    submitted_at: datetime
    rejected: bool
    rejection_reason: str | None
    adjudication_state: str
    settlement_state: str
    payable_minor: int
    lines: tuple[ClaimLineResponse, ...]

    @classmethod
    def from_view(cls, view: ClaimView) -> ClaimResponse:
        return cls(
            id=view.id,
            member_id=view.member_id,
            submitted_at=view.submitted_at,
            rejected=view.rejected,
            rejection_reason=view.rejection_reason,
            adjudication_state=view.adjudication_state,
            settlement_state=view.settlement_state,
            payable_minor=view.payable_minor,
            lines=tuple(ClaimLineResponse.from_view(line) for line in view.lines),
        )


class ClaimSummaryResponse(BaseModel):
    id: str
    member_id: str
    submitted_at: datetime
    rejected: bool
    adjudication_state: str
    settlement_state: str
    payable_minor: int

    @classmethod
    def from_view(cls, view: ClaimSummaryView) -> ClaimSummaryResponse:
        return cls(
            id=view.id,
            member_id=view.member_id,
            submitted_at=view.submitted_at,
            rejected=view.rejected,
            adjudication_state=view.adjudication_state,
            settlement_state=view.settlement_state,
            payable_minor=view.payable_minor,
        )


class ClaimListResponse(BaseModel):
    claims: tuple[ClaimSummaryResponse, ...]


class AccumulatorBalanceResponse(BaseModel):
    plan_year: int
    scope: str
    benefit_code: str | None
    consumed: int
    limit_minor: int | None
    limit_visits: int | None

    @classmethod
    def from_view(cls, view: AccumulatorBalanceView) -> AccumulatorBalanceResponse:
        return cls(
            plan_year=view.plan_year,
            scope=view.scope,
            benefit_code=view.benefit_code,
            consumed=view.consumed,
            limit_minor=view.limit_minor,
            limit_visits=view.limit_visits,
        )


class MemberAccumulatorsResponse(BaseModel):
    member_id: str
    balances: tuple[AccumulatorBalanceResponse, ...]

    @classmethod
    def from_view(cls, view: MemberAccumulatorsView) -> MemberAccumulatorsResponse:
        return cls(
            member_id=view.member_id,
            balances=tuple(
                AccumulatorBalanceResponse.from_view(balance)
                for balance in view.balances
            ),
        )


class ErrorResponse(BaseModel):
    detail: str
