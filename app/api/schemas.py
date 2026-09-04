"""Pydantic request and response models — HTTP boundary only."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.states import ReviewResolutionMode
from app.application.read_models import (
    AccumulatorBalanceView,
    AmountBreakdownView,
    ClaimLineView,
    ClaimSummaryView,
    ClaimView,
    EobLineView,
    EobPaymentView,
    EobView,
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


class LineFactCorrectionsRequest(BaseModel):
    """Facts a reviewer may correct. Computed amounts and outcomes are rejected."""

    model_config = ConfigDict(extra="forbid")

    service_code: str | None = None
    service_date: date | None = None
    provider_id: str | None = None
    billed_amount_minor: int | None = Field(default=None, ge=0)
    diagnosis_code: str | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> LineFactCorrectionsRequest:
        if not any(
            (
                self.service_code is not None,
                self.service_date is not None,
                self.provider_id is not None,
                self.billed_amount_minor is not None,
                self.diagnosis_code is not None,
            )
        ):
            raise ValueError("at least one correction field is required")
        return self


class FileDisputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_reason: str = Field(min_length=1)


class RecordPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_minor: int = Field(ge=1)
    reference: str = Field(min_length=1)
    paid_at: datetime | None = None


class EobPaymentResponse(BaseModel):
    id: str
    amount_minor: int
    paid_at: datetime
    reference: str

    @classmethod
    def from_view(cls, view: EobPaymentView) -> EobPaymentResponse:
        return cls(
            id=view.id,
            amount_minor=view.amount_minor,
            paid_at=view.paid_at,
            reference=view.reference,
        )


class EobLineResponse(BaseModel):
    line_number: int
    service_code: str
    service_date: date
    billed_minor: int
    line_state: str
    outcome: str | None
    explanations: tuple[ReasonResponse, ...]
    amounts: AmountBreakdownResponse | None

    @classmethod
    def from_view(cls, view: EobLineView) -> EobLineResponse:
        return cls(
            line_number=view.line_number,
            service_code=view.service_code,
            service_date=view.service_date,
            billed_minor=view.billed_minor,
            line_state=view.line_state,
            outcome=view.outcome,
            explanations=tuple(
                ReasonResponse.from_view(item) for item in view.explanations
            ),
            amounts=(
                None
                if view.amounts is None
                else AmountBreakdownResponse.from_view(view.amounts)
            ),
        )


class EobResponse(BaseModel):
    claim_id: str
    member_id: str
    adjudication_state: str
    settlement_state: str
    billed_minor: int
    payable_minor: int
    paid_minor: int
    member_responsibility_minor: int
    lines: tuple[EobLineResponse, ...]
    payments: tuple[EobPaymentResponse, ...]

    @classmethod
    def from_view(cls, view: EobView) -> EobResponse:
        return cls(
            claim_id=view.claim_id,
            member_id=view.member_id,
            adjudication_state=view.adjudication_state,
            settlement_state=view.settlement_state,
            billed_minor=view.billed_minor,
            payable_minor=view.payable_minor,
            paid_minor=view.paid_minor,
            member_responsibility_minor=view.member_responsibility_minor,
            lines=tuple(EobLineResponse.from_view(line) for line in view.lines),
            payments=tuple(
                EobPaymentResponse.from_view(payment) for payment in view.payments
            ),
        )


class ResolveReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ReviewResolutionMode
    reviewer_id: str = Field(min_length=1)
    note: str = Field(min_length=1)
    corrections: LineFactCorrectionsRequest | None = None

    @model_validator(mode="after")
    def mode_matches_corrections(self) -> ResolveReviewRequest:
        if self.mode is ReviewResolutionMode.CORRECT_FACTS and self.corrections is None:
            raise ValueError("corrections are required when mode is CORRECT_FACTS")
        if self.mode is ReviewResolutionMode.UPHOLD and self.corrections is not None:
            raise ValueError("uphold must not include corrections")
        return self


class ErrorResponse(BaseModel):
    detail: str
