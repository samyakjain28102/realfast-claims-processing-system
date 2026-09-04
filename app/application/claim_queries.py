"""Read-side claim queries — load persisted data and derive states."""

from __future__ import annotations

from app.application.read_models import (
    AmountBreakdownView,
    ClaimLineView,
    ClaimSummaryView,
    ClaimView,
    LineDecisionView,
    ReasonView,
    TraceStepView,
)
from app.domain.entities import LineDecision
from app.domain.lifecycle import (
    derive_adjudication_state,
    derive_line_state,
    derive_settlement_state,
    paid_from_payments,
    payable_from_decisions,
)
from app.domain.money import Money
from app.domain.reasons import ReasonCodeId, get_reason
from app.infrastructure.db import SqliteDatabase


class ClaimNotFoundError(Exception):
    """Claim id does not exist."""


class MemberNotFoundError(Exception):
    """Member id does not exist in reference data."""


def get_claim(db: SqliteDatabase, claim_id: str) -> ClaimView:
    stored = db.claims.get(claim_id)
    if stored is None:
        raise ClaimNotFoundError(claim_id)
    return _build_claim_view(db, stored.claim, stored.rejected)


def list_claims_for_member(
    db: SqliteDatabase, member_id: str
) -> tuple[ClaimSummaryView, ...]:
    if db.members.get(member_id) is None:
        raise MemberNotFoundError(member_id)
    summaries: list[ClaimSummaryView] = []
    for stored in db.claims.list_for_member(member_id):
        view = _build_claim_view(db, stored.claim, stored.rejected)
        summaries.append(
            ClaimSummaryView(
                id=view.id,
                member_id=view.member_id,
                submitted_at=view.submitted_at,
                rejected=view.rejected,
                adjudication_state=view.adjudication_state,
                settlement_state=view.settlement_state,
                payable_minor=view.payable_minor,
            )
        )
    return tuple(summaries)


def _build_claim_view(db, claim, rejected: bool) -> ClaimView:  # type: ignore[no-untyped-def]
    if rejected:
        return ClaimView(
            id=claim.id,
            member_id=claim.member_id,
            submitted_at=claim.submitted_at,
            rejected=True,
            rejection_reason=ReasonCodeId.REJ_INVALID_CLAIM.value,
            adjudication_state=derive_adjudication_state(
                rejected=True, line_states=()
            ).value,
            settlement_state=derive_settlement_state(
                Money.zero(), Money.zero()
            ).value,
            payable_minor=0,
            lines=tuple(
                ClaimLineView(
                    id=line.id,
                    line_number=line.line_number,
                    provider_id=line.provider_id,
                    service_code=line.service_code,
                    service_date=line.service_date,
                    billed_amount_minor=line.billed_amount.minor_units,
                    line_state="PENDING",
                    decision=None,
                )
                for line in claim.lines
            ),
        )

    line_views: list[ClaimLineView] = []
    current_decisions: list[LineDecision | None] = []
    for line in claim.lines:
        decision = db.decisions.current_for_line(line.id)
        has_open_dispute = bool(db.disputes.list_open_for_line(line.id))
        line_state = derive_line_state(
            decision, has_open_dispute=has_open_dispute
        )
        line_views.append(
            ClaimLineView(
                id=line.id,
                line_number=line.line_number,
                provider_id=line.provider_id,
                service_code=line.service_code,
                service_date=line.service_date,
                billed_amount_minor=line.billed_amount.minor_units,
                line_state=line_state.value,
                decision=_decision_view(decision) if decision else None,
            )
        )
        current_decisions.append(decision)

    line_states = tuple(
        derive_line_state(decision, has_open_dispute=bool(
            db.disputes.list_open_for_line(line.id)
        ))
        for line, decision in zip(claim.lines, current_decisions, strict=True)
    )
    payable = payable_from_decisions(current_decisions)
    paid = paid_from_payments(db.payments.list_for_claim(claim.id))
    return ClaimView(
        id=claim.id,
        member_id=claim.member_id,
        submitted_at=claim.submitted_at,
        rejected=False,
        rejection_reason=None,
        adjudication_state=derive_adjudication_state(
            rejected=False, line_states=line_states
        ).value,
        settlement_state=derive_settlement_state(payable, paid).value,
        payable_minor=payable.minor_units,
        lines=tuple(line_views),
    )


def _decision_view(decision: LineDecision) -> LineDecisionView:
    amounts = None
    if decision.amounts is not None:
        amounts = AmountBreakdownView(
            allowed_minor=decision.amounts.allowed.minor_units,
            above_allowed_minor=decision.amounts.above_allowed.minor_units,
            deductible_applied_minor=decision.amounts.deductible_applied.minor_units,
            plan_paid_minor=decision.amounts.plan_paid.minor_units,
            denied_amount_minor=decision.amounts.denied_amount.minor_units,
        )
    return LineDecisionView(
        id=decision.id,
        sequence=decision.sequence,
        source=decision.source.value,
        outcome=decision.outcome.value,
        reasons=tuple(
            ReasonView(
                code=reason.value,
                message=get_reason(reason).message,
                appealable=get_reason(reason).appealable,
            )
            for reason in decision.reasons
        ),
        trace=tuple(
            TraceStepView(
                step=step.step,
                rule=step.rule,
                plan_version=step.plan_version,
                inputs=step.inputs,
                result=step.result,
                accumulator_before=step.accumulator_before,
                accumulator_after=step.accumulator_after,
            )
            for step in decision.trace
        ),
        plan_version=decision.plan_version,
        decided_at=decision.decided_at,
        amounts=amounts,
    )
