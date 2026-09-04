"""Record an append-only payment against a claim's current outstanding amount."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.application.claim_queries import ClaimNotFoundError, get_claim
from app.domain.entities import Payment
from app.domain.lifecycle import paid_from_payments, payment_is_eligible
from app.domain.money import Money
from app.domain.states import ClaimAdjudicationState, SettlementState
from app.infrastructure.db import SqliteDatabase


class RecordPaymentError(Exception):
    """Payment could not be recorded."""


class PaymentWhileUnderReviewError(RecordPaymentError):
    """Payments are blocked while any line is NEEDS_REVIEW or UNDER_APPEAL."""


class PaymentNotAllowedError(RecordPaymentError):
    """Claim is not approved/partially approved with settlement DUE."""


class PaymentAmountMismatchError(RecordPaymentError):
    """Amount must equal the outstanding payable (D20)."""


@dataclass(frozen=True, slots=True)
class RecordPaymentResult:
    payment: Payment
    adjudication_state: ClaimAdjudicationState
    settlement_state: SettlementState
    payable: Money
    paid: Money


def record_payment(
    db: SqliteDatabase,
    *,
    claim_id: str,
    amount: Money,
    reference: str,
    paid_at: datetime | None = None,
    payment_id: str | None = None,
) -> RecordPaymentResult:
    """Append one payment for the exact outstanding amount, in one transaction."""
    if db.claims.get(claim_id) is None:
        raise ClaimNotFoundError(claim_id)

    paid_at = paid_at or datetime.now()
    db.begin_immediate()
    try:
        view = get_claim(db, claim_id)
        adjudication = ClaimAdjudicationState(view.adjudication_state)
        settlement = SettlementState(view.settlement_state)
        if adjudication is ClaimAdjudicationState.UNDER_REVIEW:
            raise PaymentWhileUnderReviewError(claim_id)
        if not payment_is_eligible(adjudication, settlement):
            raise PaymentNotAllowedError(claim_id)
        existing = db.payments.list_for_claim(claim_id)
        paid = paid_from_payments(existing)
        outstanding = view.payable_minor - paid.minor_units
        if amount.minor_units != outstanding:
            raise PaymentAmountMismatchError(claim_id)
        payment = Payment(
            id=payment_id or f"{claim_id}:P{len(existing) + 1}",
            claim_id=claim_id,
            amount=amount,
            paid_at=paid_at,
            reference=reference,
        )
        db.payments.add(payment)
        db.commit()
    except Exception:
        db.rollback()
        raise

    after = get_claim(db, claim_id)
    return RecordPaymentResult(
        payment=payment,
        adjudication_state=ClaimAdjudicationState(after.adjudication_state),
        settlement_state=SettlementState(after.settlement_state),
        payable=Money(after.payable_minor),
        paid=paid_from_payments(db.payments.list_for_claim(claim_id)),
    )
