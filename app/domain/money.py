"""Money value object — integer minor units only; no floating point."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Money:
    """Amount in integer minor units (e.g. paise for INR)."""

    minor_units: int

    def __post_init__(self) -> None:
        if not isinstance(self.minor_units, int):
            raise TypeError("minor_units must be int")
        if isinstance(self.minor_units, bool):
            raise TypeError("minor_units must be int, not bool")
        if self.minor_units < 0:
            raise ValueError("minor_units must be non-negative")

    @classmethod
    def zero(cls) -> Money:
        return cls(0)

    def __add__(self, other: Money) -> Money:
        return Money(self.minor_units + other.minor_units)

    def __sub__(self, other: Money) -> Money:
        result = self.minor_units - other.minor_units
        if result < 0:
            raise ValueError("money subtraction would be negative")
        return Money(result)

    def __lt__(self, other: Money) -> bool:
        return self.minor_units < other.minor_units

    def __le__(self, other: Money) -> bool:
        return self.minor_units <= other.minor_units

    def __gt__(self, other: Money) -> bool:
        return self.minor_units > other.minor_units

    def __ge__(self, other: Money) -> bool:
        return self.minor_units >= other.minor_units

    @staticmethod
    def minimum(left: Money, right: Money) -> Money:
        """Return the smaller of two amounts (used in allowed / limit arithmetic)."""
        if left <= right:
            return left
        return right
