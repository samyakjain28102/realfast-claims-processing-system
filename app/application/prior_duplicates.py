"""Build suspected-duplicate keys from prior claims. The engine does no I/O."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from app.domain.engine import SuspectedDuplicateKey, duplicate_identity
from app.domain.states import LineState

_ANCHOR_STATES = frozenset(
    {
        LineState.APPROVED,
        LineState.PARTIALLY_APPROVED,
        LineState.DENIED,
    }
)


@dataclass(frozen=True, slots=True)
class PriorLineAnchor:
    """A previously seen line. Billed amount is intentionally absent (D17)."""

    member_id: str
    provider_id: str
    service_code: str
    service_date: date
    line_state: LineState


def suspected_duplicate_keys_from_prior(
    prior_lines: Iterable[PriorLineAnchor],
) -> frozenset[SuspectedDuplicateKey]:
    """Return keys for terminal prior lines only. NEEDS_REVIEW is never an anchor."""
    keys: set[SuspectedDuplicateKey] = set()
    for line in prior_lines:
        if line.line_state not in _ANCHOR_STATES:
            continue
        keys.add(
            duplicate_identity(
                member_id=line.member_id,
                provider_id=line.provider_id,
                service_code=line.service_code,
                service_date=line.service_date,
            )
        )
    return frozenset(keys)
