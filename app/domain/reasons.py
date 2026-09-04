"""Reason code catalogue — static, CARC-informed taxonomy."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class ReasonCategory(StrEnum):
    """High-level grouping for a reason code."""

    INFO = "INFO"
    MEM = "MEM"
    DEN = "DEN"
    REV = "REV"
    REJ = "REJ"


class Liability(StrEnum):
    """Who absorbs the amount associated with this reason."""

    PLAN = "plan"
    MEMBER = "member"


class ReasonCodeId(StrEnum):
    INFO_COVERED = "INFO_COVERED"
    MEM_DEDUCTIBLE = "MEM_DEDUCTIBLE"
    MEM_ABOVE_ALLOWED = "MEM_ABOVE_ALLOWED"
    DEN_NOT_ELIGIBLE = "DEN_NOT_ELIGIBLE"
    DEN_NOT_COVERED = "DEN_NOT_COVERED"
    DEN_EXCLUDED = "DEN_EXCLUDED"
    DEN_ANNUAL_LIMIT = "DEN_ANNUAL_LIMIT"
    DEN_VISIT_LIMIT = "DEN_VISIT_LIMIT"
    DEN_DUPLICATE = "DEN_DUPLICATE"
    REV_UNKNOWN_SERVICE = "REV_UNKNOWN_SERVICE"
    REV_UNKNOWN_BENEFIT = "REV_UNKNOWN_BENEFIT"
    REV_NO_PRICE = "REV_NO_PRICE"
    REV_SUSPECTED_DUPLICATE = "REV_SUSPECTED_DUPLICATE"
    REJ_INVALID_CLAIM = "REJ_INVALID_CLAIM"


@dataclass(frozen=True, slots=True)
class ReasonCode:
    """A catalogue entry: code, message, category, liability, appealability."""

    code: ReasonCodeId
    message: str
    category: ReasonCategory
    liability: Liability | None
    appealable: bool | None


REASON_CATALOGUE: dict[ReasonCodeId, ReasonCode] = {
    ReasonCodeId.INFO_COVERED: ReasonCode(
        code=ReasonCodeId.INFO_COVERED,
        message="Covered and paid",
        category=ReasonCategory.INFO,
        liability=Liability.PLAN,
        appealable=None,
    ),
    ReasonCodeId.MEM_DEDUCTIBLE: ReasonCode(
        code=ReasonCodeId.MEM_DEDUCTIBLE,
        message="Applied to your deductible",
        category=ReasonCategory.MEM,
        liability=Liability.MEMBER,
        appealable=False,
    ),
    ReasonCodeId.MEM_ABOVE_ALLOWED: ReasonCode(
        code=ReasonCodeId.MEM_ABOVE_ALLOWED,
        message="Billed above the plan's allowed amount",
        category=ReasonCategory.MEM,
        liability=Liability.MEMBER,
        appealable=False,
    ),
    ReasonCodeId.DEN_NOT_ELIGIBLE: ReasonCode(
        code=ReasonCodeId.DEN_NOT_ELIGIBLE,
        message="No active policy on the date of service",
        category=ReasonCategory.DEN,
        liability=Liability.MEMBER,
        appealable=True,
    ),
    ReasonCodeId.DEN_NOT_COVERED: ReasonCode(
        code=ReasonCodeId.DEN_NOT_COVERED,
        message="Not a benefit under this plan",
        category=ReasonCategory.DEN,
        liability=Liability.MEMBER,
        appealable=True,
    ),
    ReasonCodeId.DEN_EXCLUDED: ReasonCode(
        code=ReasonCodeId.DEN_EXCLUDED,
        message="Explicitly excluded by this plan",
        category=ReasonCategory.DEN,
        liability=Liability.MEMBER,
        appealable=True,
    ),
    ReasonCodeId.DEN_ANNUAL_LIMIT: ReasonCode(
        code=ReasonCodeId.DEN_ANNUAL_LIMIT,
        message="Annual benefit maximum reached",
        category=ReasonCategory.DEN,
        liability=Liability.MEMBER,
        appealable=True,
    ),
    ReasonCodeId.DEN_VISIT_LIMIT: ReasonCode(
        code=ReasonCodeId.DEN_VISIT_LIMIT,
        message="Annual visit limit reached",
        category=ReasonCategory.DEN,
        liability=Liability.MEMBER,
        appealable=True,
    ),
    ReasonCodeId.DEN_DUPLICATE: ReasonCode(
        code=ReasonCodeId.DEN_DUPLICATE,
        message="Confirmed duplicate of another line on this claim",
        category=ReasonCategory.DEN,
        liability=Liability.MEMBER,
        appealable=True,
    ),
    ReasonCodeId.REV_UNKNOWN_SERVICE: ReasonCode(
        code=ReasonCodeId.REV_UNKNOWN_SERVICE,
        message="Unknown service code",
        category=ReasonCategory.REV,
        liability=None,
        appealable=None,
    ),
    ReasonCodeId.REV_UNKNOWN_BENEFIT: ReasonCode(
        code=ReasonCodeId.REV_UNKNOWN_BENEFIT,
        message="Service maps to a benefit not defined on this plan",
        category=ReasonCategory.REV,
        liability=None,
        appealable=None,
    ),
    ReasonCodeId.REV_NO_PRICE: ReasonCode(
        code=ReasonCodeId.REV_NO_PRICE,
        message="No price available for this service",
        category=ReasonCategory.REV,
        liability=None,
        appealable=None,
    ),
    ReasonCodeId.REV_SUSPECTED_DUPLICATE: ReasonCode(
        code=ReasonCodeId.REV_SUSPECTED_DUPLICATE,
        message="Suspected duplicate of a prior claim line",
        category=ReasonCategory.REV,
        liability=None,
        appealable=None,
    ),
    ReasonCodeId.REJ_INVALID_CLAIM: ReasonCode(
        code=ReasonCodeId.REJ_INVALID_CLAIM,
        message="Claim is structurally invalid",
        category=ReasonCategory.REJ,
        liability=None,
        appealable=None,
    ),
}


def get_reason(code: ReasonCodeId) -> ReasonCode:
    """Return the catalogue entry for a reason code."""
    return REASON_CATALOGUE[code]


def has_appealable_reason(reasons: Iterable[ReasonCodeId]) -> bool:
    """True if any reason is explicitly appealable. False/None do not qualify."""
    return any(get_reason(code).appealable is True for code in reasons)
