"""File a dispute against the current terminal line decision."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.claim_queries import ClaimNotFoundError
from app.domain.entities import Dispute
from app.domain.lifecycle import derive_line_state
from app.domain.reasons import has_appealable_reason
from app.domain.states import DisputeState, LineState
from app.infrastructure.db import SqliteDatabase


class FileDisputeError(Exception):
    """Dispute could not be filed."""


class DisputeLineNotFoundError(FileDisputeError):
    """line_number does not exist on the claim."""


class LineNotDisputableError(FileDisputeError):
    """Line is not in a terminal state that can be appealed."""


class DisputeNotAppealableError(FileDisputeError):
    """Current decision has no appealable reason code."""


class DisputeAlreadyOpenError(FileDisputeError):
    """An open dispute already exists on this line."""


@dataclass(frozen=True, slots=True)
class FileDisputeResult:
    dispute: Dispute
    line_id: str
    disputed_decision_id: str


def file_dispute(
    db: SqliteDatabase,
    *,
    claim_id: str,
    line_number: int,
    member_reason: str,
) -> FileDisputeResult:
    """Attach an OPEN dispute to the current decision. The decision is not mutated."""
    if not member_reason:
        raise FileDisputeError("member_reason must be non-empty")

    stored = db.claims.get(claim_id)
    if stored is None:
        raise ClaimNotFoundError(claim_id)
    if stored.rejected:
        raise LineNotDisputableError(claim_id)

    line = next(
        (item for item in stored.claim.lines if item.line_number == line_number),
        None,
    )
    if line is None:
        raise DisputeLineNotFoundError(f"{claim_id}:{line_number}")

    current = db.decisions.current_for_line(line.id)
    open_disputes = db.disputes.list_open_for_line(line.id)
    line_state = derive_line_state(current, has_open_dispute=bool(open_disputes))
    if line_state is LineState.UNDER_APPEAL:
        raise DisputeAlreadyOpenError(line.id)
    if line_state not in {
        LineState.APPROVED,
        LineState.PARTIALLY_APPROVED,
        LineState.DENIED,
    }:
        raise LineNotDisputableError(line.id)
    if current is None or not has_appealable_reason(current.reasons):
        raise DisputeNotAppealableError(line.id)

    dispute = Dispute(
        id=f"{line.id}:D{len(db.disputes.list_for_line(line.id)) + 1}",
        line_id=line.id,
        disputed_decision_id=current.id,
        member_reason=member_reason,
        state=DisputeState.OPEN,
    )
    db.begin_immediate()
    try:
        db.disputes.add(dispute)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return FileDisputeResult(
        dispute=dispute,
        line_id=line.id,
        disputed_decision_id=current.id,
    )
