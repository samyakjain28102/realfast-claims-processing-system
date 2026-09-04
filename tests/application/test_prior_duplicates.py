"""Application-layer prior-claim keys: only terminal lines become anchors."""

from datetime import date

from app.application.prior_duplicates import (
    PriorLineAnchor,
    suspected_duplicate_keys_from_prior,
)
from app.domain.engine import duplicate_identity
from app.domain.states import LineState


def _anchor(state: LineState, *, day: int = 15) -> PriorLineAnchor:
    return PriorLineAnchor(
        member_id="m1",
        provider_id="prov1",
        service_code="PHYSIO-30",
        service_date=date(2026, 3, day),
        line_state=state,
    )


def test_terminal_prior_lines_become_suspected_keys() -> None:
    keys = suspected_duplicate_keys_from_prior(
        (
            _anchor(LineState.APPROVED),
            _anchor(LineState.PARTIALLY_APPROVED, day=16),
            _anchor(LineState.DENIED, day=17),
        )
    )
    assert keys == frozenset(
        {
            duplicate_identity(
                member_id="m1",
                provider_id="prov1",
                service_code="PHYSIO-30",
                service_date=date(2026, 3, 15),
            ),
            duplicate_identity(
                member_id="m1",
                provider_id="prov1",
                service_code="PHYSIO-30",
                service_date=date(2026, 3, 16),
            ),
            duplicate_identity(
                member_id="m1",
                provider_id="prov1",
                service_code="PHYSIO-30",
                service_date=date(2026, 3, 17),
            ),
        }
    )


def test_needs_review_and_under_appeal_are_not_anchors() -> None:
    keys = suspected_duplicate_keys_from_prior(
        (
            _anchor(LineState.NEEDS_REVIEW),
            _anchor(LineState.UNDER_APPEAL, day=16),
            _anchor(LineState.PENDING, day=17),
        )
    )
    assert keys == frozenset()
