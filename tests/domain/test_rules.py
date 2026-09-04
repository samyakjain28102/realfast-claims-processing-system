from datetime import date

import pytest

from app.domain.money import Money
from app.domain.rules import Benefit


def test_benefit_with_dollar_and_visit_limits() -> None:
    benefit = Benefit(
        code="PHYSIO",
        name="Physiotherapy",
        covered=True,
        excluded=False,
        annual_limit_amount=Money(100_000),
        annual_visit_limit=12,
    )
    assert benefit.code == "PHYSIO"
    assert benefit.annual_limit_amount == Money(100_000)


def test_benefit_rejects_empty_code() -> None:
    with pytest.raises(ValueError, match="code"):
        Benefit(
            code="",
            name="Physio",
            covered=True,
            excluded=False,
            annual_limit_amount=None,
            annual_visit_limit=None,
        )


def test_benefit_rejects_negative_visit_limit() -> None:
    with pytest.raises(ValueError, match="annual_visit_limit"):
        Benefit(
            code="PHYSIO",
            name="Physio",
            covered=True,
            excluded=False,
            annual_limit_amount=None,
            annual_visit_limit=-1,
        )
