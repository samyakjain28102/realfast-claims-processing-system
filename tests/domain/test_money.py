import pytest

from app.domain.money import Money


def test_zero_is_non_negative() -> None:
    assert Money.zero().minor_units == 0


def test_addition() -> None:
    assert (Money(400) + Money(100)).minor_units == 500


def test_subtraction() -> None:
    assert (Money(500) - Money(100)).minor_units == 400


def test_subtraction_rejects_negative_result() -> None:
    with pytest.raises(ValueError, match="negative"):
        Money(100) - Money(200)


def test_minimum_returns_smaller_amount() -> None:
    assert Money.minimum(Money(300), Money(500)) == Money(300)
    assert Money.minimum(Money(500), Money(300)) == Money(300)


def test_rejects_negative_minor_units() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Money(-1)


def test_rejects_bool_as_minor_units() -> None:
    with pytest.raises(TypeError, match="bool"):
        Money(True)  # type: ignore[arg-type]


def test_rejects_float_as_minor_units() -> None:
    with pytest.raises(TypeError):
        Money(1.5)  # type: ignore[arg-type]


def test_money_is_immutable() -> None:
    amount = Money(100)
    with pytest.raises(AttributeError):
        amount.minor_units = 200  # type: ignore[misc]
