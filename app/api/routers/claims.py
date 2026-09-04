"""Claim HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_db
from app.api.schemas import (
    ClaimListResponse,
    ClaimResponse,
    ClaimSummaryResponse,
    EobResponse,
    FileDisputeRequest,
    RecordPaymentRequest,
    SubmitClaimRequest,
)
from app.application.build_eob import build_eob
from app.application.claim_queries import get_claim, list_claims_for_member
from app.application.file_dispute import file_dispute
from app.application.record_payment import record_payment
from app.application.submit_claim import submit_claim
from app.domain.entities import Claim, ClaimLine
from app.domain.money import Money
from app.infrastructure.db import SqliteDatabase

router = APIRouter(prefix="/claims", tags=["claims"])


def _claim_from_request(body: SubmitClaimRequest) -> Claim:
    lines = tuple(
        ClaimLine(
            id=f"{body.id}-L{line.line_number}",
            claim_id=body.id,
            line_number=line.line_number,
            provider_id=line.provider_id,
            service_code=line.service_code,
            service_date=line.service_date,
            billed_amount=Money(line.billed_amount_minor),
            diagnosis_code=line.diagnosis_code,
        )
        for line in body.lines
    )
    return Claim(
        id=body.id,
        member_id=body.member_id,
        submitted_at=body.submitted_at,
        lines=lines,
    )


@router.post("", response_model=ClaimResponse, status_code=201)
def post_claim(
    body: SubmitClaimRequest,
    db: SqliteDatabase = Depends(get_db),
) -> ClaimResponse:
    submit_claim(db, _claim_from_request(body))
    return ClaimResponse.from_view(get_claim(db, body.id))


@router.get("/{claim_id}", response_model=ClaimResponse)
def get_claim_by_id(
    claim_id: str,
    db: SqliteDatabase = Depends(get_db),
) -> ClaimResponse:
    return ClaimResponse.from_view(get_claim(db, claim_id))


@router.post(
    "/{claim_id}/lines/{line_number}/disputes",
    response_model=ClaimResponse,
    status_code=201,
)
def post_line_dispute(
    claim_id: str,
    line_number: int,
    body: FileDisputeRequest,
    db: SqliteDatabase = Depends(get_db),
) -> ClaimResponse:
    file_dispute(
        db,
        claim_id=claim_id,
        line_number=line_number,
        member_reason=body.member_reason,
    )
    return ClaimResponse.from_view(get_claim(db, claim_id))


@router.post(
    "/{claim_id}/payments",
    response_model=ClaimResponse,
    status_code=201,
)
def post_claim_payment(
    claim_id: str,
    body: RecordPaymentRequest,
    db: SqliteDatabase = Depends(get_db),
) -> ClaimResponse:
    record_payment(
        db,
        claim_id=claim_id,
        amount=Money(body.amount_minor),
        reference=body.reference,
        paid_at=body.paid_at,
    )
    return ClaimResponse.from_view(get_claim(db, claim_id))


@router.get("/{claim_id}/eob", response_model=EobResponse)
def get_claim_eob(
    claim_id: str,
    db: SqliteDatabase = Depends(get_db),
) -> EobResponse:
    return EobResponse.from_view(build_eob(db, claim_id))


@router.get("", response_model=ClaimListResponse)
def list_claims(
    member_id: str,
    db: SqliteDatabase = Depends(get_db),
) -> ClaimListResponse:
    claims = list_claims_for_member(db, member_id)
    return ClaimListResponse(
        claims=tuple(ClaimSummaryResponse.from_view(item) for item in claims)
    )
