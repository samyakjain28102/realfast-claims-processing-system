"""Generic quantity-against-limit accumulators."""

from __future__ import annotations

from collections.abc import Iterable
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


def apply_quantity(*, limit: int, consumed: int, requested: int) -> tuple[int, int]:
    """Apply a requested quantity against a limit. Same math for money and visits.

    Returns ``(applied, consumed_after)``. ``consumed_after`` is never reduced here;
    reversal is a separate compensating append.
    """
    if limit < 0:
        raise ValueError("limit must be non-negative")
    if consumed < 0:
        raise ValueError("consumed must be non-negative")
    if requested < 0:
        raise ValueError("requested must be non-negative")
    available = max(0, limit - consumed)
    applied = min(requested, available)
    return applied, consumed + applied


def ledger_balance(entries: Iterable[AccumulatorEntry], key: AccumulatorKey) -> int:
    """Balance for a key is the sum of quantities — money minor units or visit counts."""
    return sum(entry.quantity for entry in entries if entry.key == key)


def compensating_entry(
    original: AccumulatorEntry,
    *,
    id: str,
    decision_id: str,
) -> AccumulatorEntry:
    """Reverse by posting the negated quantity. The original row is not deleted."""
    return AccumulatorEntry(
        id=id,
        key=original.key,
        quantity=-original.quantity,
        decision_id=decision_id,
        reverses_entry_id=original.id,
    )


@dataclass(frozen=True, slots=True)
class AccumulatorLedger:
    """Append-only in-memory ledger. There is no delete or in-place update."""

    entries: tuple[AccumulatorEntry, ...] = ()

    def append(self, entry: AccumulatorEntry) -> AccumulatorLedger:
        return AccumulatorLedger(self.entries + (entry,))

    def balance(self, key: AccumulatorKey) -> int:
        return ledger_balance(self.entries, key)

    def reverse(
        self,
        original: AccumulatorEntry,
        *,
        id: str,
        decision_id: str,
    ) -> AccumulatorLedger:
        return self.append(
            compensating_entry(original, id=id, decision_id=decision_id)
        )
