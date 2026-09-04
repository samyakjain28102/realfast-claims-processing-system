import pytest

from app.domain.accumulators import (
    AccumulatorEntry,
    AccumulatorKey,
    AccumulatorLedger,
    AccumulatorScope,
    apply_quantity,
    compensating_entry,
)


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


def test_apply_quantity_is_generic_over_money_and_visits() -> None:
    money_applied, money_after = apply_quantity(
        limit=10_000,
        consumed=6_000,
        requested=5_000,
    )
    visit_applied, visit_after = apply_quantity(
        limit=12,
        consumed=11,
        requested=1,
    )
    assert money_applied == 4_000
    assert money_after == 10_000
    assert visit_applied == 1
    assert visit_after == 12


def test_append_only_reversal_is_a_compensating_entry() -> None:
    key = AccumulatorKey("m1", 2026, AccumulatorScope.DEDUCTIBLE, None)
    original = AccumulatorEntry(
        id="ae1",
        key=key,
        quantity=4_000,
        decision_id="dec1",
    )
    ledger = AccumulatorLedger().append(original)
    reversed_ledger = ledger.reverse(original, id="ae2", decision_id="dec2")

    assert ledger.balance(key) == 4_000
    assert reversed_ledger.balance(key) == 0
    assert reversed_ledger.entries[0] is original
    assert reversed_ledger.entries[1] == compensating_entry(
        original, id="ae2", decision_id="dec2"
    )
    assert not hasattr(AccumulatorLedger, "remove")
    assert not hasattr(AccumulatorLedger, "delete")


def test_visit_count_reversal_uses_the_same_ledger() -> None:
    key = AccumulatorKey("m1", 2026, AccumulatorScope.BENEFIT_VISITS, "PHYSIO")
    original = AccumulatorEntry(id="ae1", key=key, quantity=1, decision_id="dec1")
    ledger = AccumulatorLedger().append(original).reverse(
        original, id="ae2", decision_id="dec2"
    )
    assert ledger.balance(key) == 0
    assert ledger.entries[1].quantity == -1
    assert ledger.entries[1].reverses_entry_id == "ae1"
