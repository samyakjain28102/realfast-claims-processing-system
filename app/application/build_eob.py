"""Build a member-facing EOB from persisted decisions and payments."""

from __future__ import annotations

from app.application.claim_queries import get_claim
from app.application.read_models import EobLineView, EobPaymentView, EobView
from app.domain.lifecycle import paid_from_payments
from app.infrastructure.db import SqliteDatabase


def build_eob(db: SqliteDatabase, claim_id: str) -> EobView:
    """Aggregate current claim facts. Does not adjudicate or create decisions."""
    view = get_claim(db, claim_id)
    payments = db.payments.list_for_claim(claim_id)
    lines: list[EobLineView] = []
    member_responsibility = 0
    billed_total = 0
    for line in view.lines:
        billed_total += line.billed_amount_minor
        amounts = None if line.decision is None else line.decision.amounts
        explanations = ()
        if line.decision is not None:
            explanations = line.decision.reasons
            if amounts is not None:
                member_responsibility += (
                    line.billed_amount_minor - amounts.plan_paid_minor
                )
        lines.append(
            EobLineView(
                line_number=line.line_number,
                service_code=line.service_code,
                service_date=line.service_date,
                billed_minor=line.billed_amount_minor,
                line_state=line.line_state,
                outcome=None if line.decision is None else line.decision.outcome,
                explanations=explanations,
                amounts=amounts,
            )
        )
    return EobView(
        claim_id=view.id,
        member_id=view.member_id,
        adjudication_state=view.adjudication_state,
        settlement_state=view.settlement_state,
        billed_minor=billed_total,
        payable_minor=view.payable_minor,
        paid_minor=paid_from_payments(payments).minor_units,
        member_responsibility_minor=member_responsibility,
        lines=tuple(lines),
        payments=tuple(
            EobPaymentView(
                id=payment.id,
                amount_minor=payment.amount.minor_units,
                paid_at=payment.paid_at,
                reference=payment.reference,
            )
            for payment in payments
        ),
    )
