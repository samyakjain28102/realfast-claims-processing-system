"""Generic quantity-against-limit accumulators."""

from __future__ import annotations

from enum import StrEnum


class AccumulatorScope(StrEnum):
    """What an accumulator key measures against a limit."""

    DEDUCTIBLE = "DEDUCTIBLE"
    BENEFIT_AMOUNT = "BENEFIT_AMOUNT"
    BENEFIT_VISITS = "BENEFIT_VISITS"
