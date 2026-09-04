"""Generic quantity-against-limit accumulators."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AccumulatorScope(StrEnum):
    """What an accumulator key measures against a limit."""

    DEDUCTIBLE = "DEDUCTIBLE"
    BENEFIT_AMOUNT = "BENEFIT_AMOUNT"
    BENEFIT_VISITS = "BENEFIT_VISITS"


@dataclass(frozen=True, slots=True)
class AccumulatorKey:
    """Identifies a member's running total against a limit for a plan year."""

    member_id: str
    plan_year: int
    scope: AccumulatorScope
    benefit_code: str | None

    def __post_init__(self) -> None:
        if not self.member_id:
            raise ValueError("member_id must be non-empty")
        if self.scope is AccumulatorScope.DEDUCTIBLE:
            if self.benefit_code is not None:
                raise ValueError("deductible accumulator must not have benefit_code")
        elif self.benefit_code is None or not self.benefit_code:
            raise ValueError("benefit accumulator requires benefit_code")


@dataclass(frozen=True, slots=True)
class AccumulatorEntry:
    """Append-only ledger row. Balance for a key is the sum of quantities."""

    id: str
    key: AccumulatorKey
    quantity: int
    decision_id: str
    reverses_entry_id: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id must be non-empty")
        if not self.decision_id:
            raise ValueError("decision_id must be non-empty")
        if self.quantity == 0:
            raise ValueError("quantity must be non-zero")
        if self.reverses_entry_id is not None and not self.reverses_entry_id:
            raise ValueError("reverses_entry_id must be non-empty when set")
