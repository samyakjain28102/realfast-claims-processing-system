"""Review resolution HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_db
from app.api.schemas import ClaimResponse, ResolveReviewRequest
from app.application.claim_queries import get_claim
from app.application.resolve_review import resolve_review
from app.domain.entities import LineFactCorrections
from app.domain.money import Money
from app.infrastructure.db import SqliteDatabase

router = APIRouter(prefix="/reviews", tags=["reviews"])


def _corrections_from_request(
    body: ResolveReviewRequest,
) -> LineFactCorrections | None:
    raw = body.corrections
    if raw is None:
        return None
    return LineFactCorrections(
        service_code=raw.service_code,
        service_date=raw.service_date,
        provider_id=raw.provider_id,
        billed_amount=(
            None if raw.billed_amount_minor is None else Money(raw.billed_amount_minor)
        ),
        diagnosis_code=raw.diagnosis_code,
    )


@router.post("/{line_id}/resolve", response_model=ClaimResponse)
def post_resolve_review(
    line_id: str,
    body: ResolveReviewRequest,
    db: SqliteDatabase = Depends(get_db),
) -> ClaimResponse:
    result = resolve_review(
        db,
        line_id=line_id,
        mode=body.mode,
        reviewer_id=body.reviewer_id,
        note=body.note,
        corrections=_corrections_from_request(body),
    )
    return ClaimResponse.from_view(get_claim(db, result.claim.id))
