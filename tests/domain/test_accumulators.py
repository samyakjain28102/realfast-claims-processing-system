import pytest

from app.domain.accumulators import AccumulatorEntry, AccumulatorKey, AccumulatorScope


def test_deductible_key_has_no_benefit_code() -> None:
    key = AccumulatorKey(
        member_id="m1",
        plan_year=2026,
        scope=AccumulatorScope.DEDUCTIBLE,
        benefit_code=None,
    )
    assert key.benefit_code is None


def test_deductible_key_rejects_benefit_code() -> None:
    with pytest.raises(ValueError, match="benefit_code"):
        AccumulatorKey(
            member_id="m1",
            plan_year=2026,
            scope=AccumulatorScope.DEDUCTIBLE,
            benefit_code="PHYSIO",
        )


def test_benefit_amount_key_requires_benefit_code() -> None:
    with pytest.raises(ValueError, match="benefit_code"):
        AccumulatorKey(
            member_id="m1",
            plan_year=2026,
            scope=AccumulatorScope.BENEFIT_AMOUNT,
            benefit_code=None,
        )


def test_ledger_entry_links_to_decision() -> None:
    key = AccumulatorKey("m1", 2026, AccumulatorScope.BENEFIT_VISITS, "PHYSIO")
    entry = AccumulatorEntry(
        id="ae1",
        key=key,
        quantity=1,
        decision_id="dec1",
    )
    assert entry.decision_id == "dec1"
    assert entry.reverses_entry_id is None


def test_reversal_entry_references_original() -> None:
    key = AccumulatorKey("m1", 2026, AccumulatorScope.BENEFIT_AMOUNT, "PHYSIO")
    entry = AccumulatorEntry(
        id="ae2",
        key=key,
        quantity=-4_000,
        decision_id="dec2",
        reverses_entry_id="ae1",
    )
    assert entry.reverses_entry_id == "ae1"


def test_entry_rejects_zero_quantity() -> None:
    key = AccumulatorKey("m1", 2026, AccumulatorScope.DEDUCTIBLE, None)
    with pytest.raises(ValueError, match="quantity"):
        AccumulatorEntry(id="ae1", key=key, quantity=0, decision_id="dec1")
