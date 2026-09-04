"""Mechanical mapping between sqlite3 rows and domain dataclasses."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from app.domain.accumulators import AccumulatorEntry, AccumulatorKey, AccumulatorScope
from app.domain.entities import (
    Claim,
    ClaimLine,
    DecisionAmounts,
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


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def money_or_none(minor: int | None) -> Money | None:
    if minor is None:
        return None
    return Money(minor)


def bool_from_int(value: int) -> bool:
    return bool(value)


def int_from_bool(value: bool) -> int:
    return 1 if value else 0


def member_from_row(row: Any) -> Member:
    return Member(
        id=row["id"],
        name=row["name"],
        date_of_birth=parse_date(row["date_of_birth"]),
    )


def provider_from_row(row: Any) -> Provider:
    return Provider(id=row["id"], name=row["name"])


def benefit_from_row(row: Any) -> Benefit:
    return Benefit(
        code=row["code"],
        name=row["name"],
        covered=bool_from_int(row["covered"]),
        excluded=bool_from_int(row["excluded"]),
        annual_limit_amount=money_or_none(row["annual_limit_amount_minor"]),
        annual_visit_limit=row["annual_visit_limit"],
    )


def plan_from_rows(plan_row: Any, benefit_rows: list[Any]) -> Plan:
    return Plan(
        id=plan_row["id"],
        version=plan_row["version"],
        deductible=Money(plan_row["deductible_minor"]),
        benefits=tuple(benefit_from_row(row) for row in benefit_rows),
    )


def policy_from_row(row: Any) -> Policy:
    termination = row["termination_date"]
    return Policy(
        id=row["id"],
        member_id=row["member_id"],
        plan_id=row["plan_id"],
        effective_date=parse_date(row["effective_date"]),
        termination_date=parse_date(termination) if termination else None,
    )


def catalogue_entry_from_row(row: Any) -> ServiceCatalogueEntry:
    return ServiceCatalogueEntry(
        service_code=row["service_code"],
        description=row["description"],
        benefit_code=row["benefit_code"],
        scheduled_amount=money_or_none(row["scheduled_amount_minor"]),
    )


def claim_line_from_row(row: Any) -> ClaimLine:
    return ClaimLine(
        id=row["id"],
        claim_id=row["claim_id"],
        line_number=row["line_number"],
        provider_id=row["provider_id"],
        service_code=row["service_code"],
        service_date=parse_date(row["service_date"]),
        billed_amount=Money(row["billed_amount_minor"]),
        diagnosis_code=row["diagnosis_code"],
    )


def claim_from_rows(claim_row: Any, line_rows: list[Any]) -> Claim:
    return Claim(
        id=claim_row["id"],
        member_id=claim_row["member_id"],
        submitted_at=parse_datetime(claim_row["submitted_at"]),
        lines=tuple(claim_line_from_row(row) for row in line_rows),
    )


def amounts_from_row(row: Any) -> DecisionAmounts | None:
    if row["allowed_minor"] is None:
        return None
    return DecisionAmounts(
        allowed=Money(row["allowed_minor"]),
        above_allowed=Money(row["above_allowed_minor"]),
        deductible_applied=Money(row["deductible_applied_minor"]),
        plan_paid=Money(row["plan_paid_minor"]),
        denied_amount=Money(row["denied_amount_minor"]),
    )


def amounts_to_columns(
    amounts: DecisionAmounts | None,
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    if amounts is None:
        return (None, None, None, None, None)
    return (
        amounts.allowed.minor_units,
        amounts.above_allowed.minor_units,
        amounts.deductible_applied.minor_units,
        amounts.plan_paid.minor_units,
        amounts.denied_amount.minor_units,
    )


def reasons_to_json(reasons: tuple[ReasonCodeId, ...]) -> str:
    return json.dumps([reason.value for reason in reasons])


def reasons_from_json(payload: str) -> tuple[ReasonCodeId, ...]:
    return tuple(ReasonCodeId(code) for code in json.loads(payload))


def trace_to_json(trace: tuple[TraceStep, ...]) -> str:
    return json.dumps(
        [
            {
                "step": step.step,
                "rule": step.rule,
                "plan_version": step.plan_version,
                "inputs": step.inputs,
                "result": step.result,
                "accumulator_before": step.accumulator_before,
                "accumulator_after": step.accumulator_after,
            }
            for step in trace
        ]
    )


def trace_from_json(payload: str) -> tuple[TraceStep, ...]:
    return tuple(
        TraceStep(
            step=item["step"],
            rule=item["rule"],
            plan_version=item["plan_version"],
            inputs=item["inputs"],
            result=item["result"],
            accumulator_before=item.get("accumulator_before"),
            accumulator_after=item.get("accumulator_after"),
        )
        for item in json.loads(payload)
    )


def line_decision_from_row(row: Any) -> LineDecision:
    return LineDecision(
        id=row["id"],
        line_id=row["line_id"],
        sequence=row["sequence"],
        source=DecisionSource(row["source"]),
        outcome=LineOutcome(row["outcome"]),
        reasons=reasons_from_json(row["reasons_json"]),
        trace=trace_from_json(row["trace_json"]),
        plan_version=row["plan_version"],
        decided_at=parse_datetime(row["decided_at"]),
        decided_by=row["decided_by"],
        amounts=amounts_from_row(row),
    )


def accumulator_entry_from_row(row: Any) -> AccumulatorEntry:
    return AccumulatorEntry(
        id=row["id"],
        key=AccumulatorKey(
            member_id=row["member_id"],
            plan_year=row["plan_year"],
            scope=AccumulatorScope(row["scope"]),
            benefit_code=row["benefit_code"],
        ),
        quantity=row["quantity"],
        decision_id=row["decision_id"],
        reverses_entry_id=row["reverses_entry_id"],
    )


def payment_from_row(row: Any) -> Payment:
    return Payment(
        id=row["id"],
        claim_id=row["claim_id"],
        amount=Money(row["amount_minor"]),
        paid_at=parse_datetime(row["paid_at"]),
        reference=row["reference"],
    )


def dispute_from_row(row: Any) -> Dispute:
    return Dispute(
        id=row["id"],
        line_id=row["line_id"],
        disputed_decision_id=row["disputed_decision_id"],
        member_reason=row["member_reason"],
        state=DisputeState(row["state"]),
    )


def corrections_from_row(row: Any) -> LineFactCorrections | None:
    service_code = row["correction_service_code"]
    service_date = row["correction_service_date"]
    provider_id = row["correction_provider_id"]
    billed = row["correction_billed_amount_minor"]
    diagnosis = row["correction_diagnosis_code"]
    if (
        service_code is None
        and service_date is None
        and provider_id is None
        and billed is None
        and diagnosis is None
    ):
        return None
    return LineFactCorrections(
        service_code=service_code,
        service_date=parse_date(service_date) if service_date else None,
        provider_id=provider_id,
        billed_amount=Money(billed) if billed is not None else None,
        diagnosis_code=diagnosis,
    )


def review_resolution_from_row(row: Any) -> ReviewResolution:
    return ReviewResolution(
        id=row["id"],
        line_id=row["line_id"],
        mode=ReviewResolutionMode(row["mode"]),
        reviewer_id=row["reviewer_id"],
        note=row["note"],
        resulting_decision_id=row["resulting_decision_id"],
        dispute_id=row["dispute_id"],
        corrections=corrections_from_row(row),
    )
