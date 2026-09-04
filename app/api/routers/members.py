"""Member HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_db
from app.api.schemas import MemberAccumulatorsResponse
from app.application.get_member_accumulators import get_member_accumulators
from app.infrastructure.db import SqliteDatabase

router = APIRouter(prefix="/members", tags=["members"])


@router.get("/{member_id}/accumulators", response_model=MemberAccumulatorsResponse)
def member_accumulators(
    member_id: str,
    db: SqliteDatabase = Depends(get_db),
) -> MemberAccumulatorsResponse:
    return MemberAccumulatorsResponse.from_view(
        get_member_accumulators(db, member_id)
    )
