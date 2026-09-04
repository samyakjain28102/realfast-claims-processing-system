"""Typed coverage rule objects (Benefit)."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.money import Money


@dataclass(frozen=True, slots=True)
class Benefit:
    """A plan's promise about a category of service — the coverage rule."""

    code: str
    name: str
    covered: bool
    excluded: bool
    annual_limit_amount: Money | None
    annual_visit_limit: int | None

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("code must be non-empty")
        if self.annual_visit_limit is not None and self.annual_visit_limit < 0:
            raise ValueError("annual_visit_limit must be non-negative when set")
