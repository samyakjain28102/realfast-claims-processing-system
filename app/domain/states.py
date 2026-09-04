"""Domain enums for line outcomes and claim lifecycles. Derivation lives in lifecycle.py."""

from __future__ import annotations

from enum import StrEnum


class LineOutcome(StrEnum):
    """Coverage determination on a line decision."""

    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class LineState(StrEnum):
    """Derived line lifecycle — includes pre-adjudication and appeal states."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    UNDER_APPEAL = "UNDER_APPEAL"


class ClaimAdjudicationState(StrEnum):
    """Derived claim adjudication lifecycle."""

    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"


class SettlementState(StrEnum):
    """Derived claim settlement lifecycle."""

    NOTHING_DUE = "NOTHING_DUE"
    DUE = "DUE"
    SETTLED = "SETTLED"
    OVERPAID = "OVERPAID"


class DecisionSource(StrEnum):
    """Origin of a line decision's monetary outcome."""

    RULES = "RULES"
    # HUMAN_OVERRIDE deferred per D21.


class DisputeState(StrEnum):
    """Lifecycle of a member dispute on a line decision."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReviewResolutionMode(StrEnum):
    """How a review or dispute was resolved."""

    CORRECT_FACTS = "CORRECT_FACTS"
    UPHOLD = "UPHOLD"
