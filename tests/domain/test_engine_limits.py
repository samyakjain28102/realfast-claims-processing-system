"""Gates 8–9: visit limits, dollar limits, and multi-line working balances."""

from __future__ import annotations

from datetime import date, datetime

from app.domain.accumulators import AccumulatorKey, AccumulatorScope
from app.domain.engine import AdjudicationContext, adjudicate
from app.domain.entities import Claim, ClaimLine, Plan, Policy, ServiceCatalogueEntry
from app.domain.money import Money
from app.domain.reasons import ReasonCodeId
from app.domain.rules import Benefit
from app.domain.states import LineOutcome


def _benefit(
    code: str = "PHYSIO",
    *,
    annual_limit_amount: Money | None = Money(100_000),
    annual_visit_limit: int | None = 12,
) -> Benefit:
    return Benefit(
        code=code,
        name=code.title(),
        covered=True,
        excluded=False,
        annual_limit_amount=annual_limit_amount,
        annual_visit_limit=annual_visit_limit,
    )


def _plan(*, deductible: Money = Money.zero(), benefits: tuple[Benefit, ...]) -> Plan:
    return Plan(id="plan1", version=3, deductible=deductible, benefits=benefits)


def _policy(*, effective_date: date = date(2026, 1, 1)) -> Policy:
    return Policy(
        id="pol1",
        member_id="m1",
        plan_id="plan1",
        effective_date=effective_date,
        termination_date=None,
    )


def _catalogue() -> dict[str, ServiceCatalogueEntry]:
    return {
        "PHYSIO-30": ServiceCatalogueEntry(
            service_code="PHYSIO-30",
            description="Physio session",
            benefit_code="PHYSIO",
            scheduled_amount=Money(4_000),
        ),
        "DIAG-1": ServiceCatalogueEntry(
            service_code="DIAG-1",
            description="Diagnostics",
            benefit_code="DIAGNOSTICS",
            scheduled_amount=Money(8_000),
        ),
    }


def _ctx(**overrides: object) -> AdjudicationContext:
    defaults: dict[str, object] = {
        "policy": _policy(),
        "plan": _plan(benefits=(_benefit(),)),
        "catalogue": _catalogue(),
        "suspected_duplicate_keys": frozenset(),
        "as_of": date(2026, 3, 20),
        "decided_at": datetime(2026, 3, 20, 10, 0),
        "decided_by": "rules",
        "accumulator_consumed": {},
    }
    defaults.update(overrides)
    return AdjudicationContext(**defaults)  # type: ignore[arg-type]


def _line(**overrides: object) -> ClaimLine:
    defaults = {
        "id": "line1",
        "claim_id": "claim1",
        "line_number": 1,
        "provider_id": "prov1",
        "service_code": "PHYSIO-30",
        "service_date": date(2026, 3, 15),
        "billed_amount": Money(4_000),
        "diagnosis_code": "M54.5",
    }
    defaults.update(overrides)
    return ClaimLine(**defaults)  # type: ignore[arg-type]


def _claim(*lines: ClaimLine) -> Claim:
    return Claim(
        id="claim1",
        member_id="m1",
        submitted_at=datetime(2026, 3, 20, 9, 0),
        lines=lines,
    )


def _amount_key(plan_year: int = 2026, benefit: str = "PHYSIO") -> AccumulatorKey:
    return AccumulatorKey("m1", plan_year, AccumulatorScope.BENEFIT_AMOUNT, benefit)


def _visit_key(plan_year: int = 2026, benefit: str = "PHYSIO") -> AccumulatorKey:
    return AccumulatorKey("m1", plan_year, AccumulatorScope.BENEFIT_VISITS, benefit)


def _deductible_key(plan_year: int = 2026) -> AccumulatorKey:
    return AccumulatorKey("m1", plan_year, AccumulatorScope.DEDUCTIBLE, None)


def test_dollar_limit_below_limit_pays_full_after_deductible() -> None:
    ctx = _ctx(plan=_plan(benefits=(_benefit(annual_limit_amount=Money(10_000)),)))
    result = adjudicate(_claim(_line()), ctx)
    decision = result.line_results[0].decision
    assert decision is not None
    assert decision.outcome is LineOutcome.APPROVED
    assert decision.amounts is not None
    assert decision.amounts.plan_paid == Money(4_000)
    assert decision.amounts.denied_amount == Money.zero()
    assert ReasonCodeId.INFO_COVERED in decision.reasons
    decision.amounts.check_conservation(Money(4_000))


def test_dollar_limit_exactly_at_limit_pays_the_remainder() -> None:
    ctx = _ctx(
        plan=_plan(benefits=(_benefit(annual_limit_amount=Money(10_000)),)),
        accumulator_consumed={_amount_key(): 6_000},
    )
    result = adjudicate(_claim(_line()), ctx)
    decision = result.line_results[0].decision
    assert decision is not None
    assert decision.amounts is not None
    assert decision.amounts.plan_paid == Money(4_000)
    assert decision.amounts.denied_amount == Money.zero()
    assert decision.outcome is LineOutcome.APPROVED


def test_dollar_limit_partially_remaining_partially_approves() -> None:
    ctx = _ctx(
        plan=_plan(benefits=(_benefit(annual_limit_amount=Money(10_000)),)),
        accumulator_consumed={_amount_key(): 9_000},
    )
    result = adjudicate(_claim(_line()), ctx)
    decision = result.line_results[0].decision
    assert decision is not None
    assert decision.outcome is LineOutcome.PARTIALLY_APPROVED
    assert decision.amounts is not None
    assert decision.amounts.plan_paid == Money(1_000)
    assert decision.amounts.denied_amount == Money(3_000)
    assert ReasonCodeId.DEN_ANNUAL_LIMIT in decision.reasons
    decision.amounts.check_conservation(Money(4_000))
    amount_deltas = [
        delta
        for delta in result.accumulator_deltas
        if delta.key.scope is AccumulatorScope.BENEFIT_AMOUNT
    ]
    assert amount_deltas[0].quantity == 1_000


def test_dollar_limit_exhausted_denies_after_deductible() -> None:
    ctx = _ctx(
        plan=_plan(benefits=(_benefit(annual_limit_amount=Money(10_000)),)),
        accumulator_consumed={_amount_key(): 10_000},
    )
    result = adjudicate(_claim(_line()), ctx)
    decision = result.line_results[0].decision
    assert decision is not None
    assert decision.outcome is LineOutcome.DENIED
    assert decision.amounts is not None
    assert decision.amounts.plan_paid == Money.zero()
    assert decision.amounts.denied_amount == Money(4_000)
    assert ReasonCodeId.DEN_ANNUAL_LIMIT in decision.reasons
    assert not any(
        delta.key.scope is AccumulatorScope.BENEFIT_AMOUNT
        for delta in result.accumulator_deltas
    )


def test_visit_limit_below_limit_approves_and_consumes_one_visit() -> None:
    ctx = _ctx(accumulator_consumed={_visit_key(): 3})
    result = adjudicate(_claim(_line()), ctx)
    decision = result.line_results[0].decision
    assert decision is not None
    assert decision.outcome is LineOutcome.APPROVED
    visit_deltas = [
        delta
        for delta in result.accumulator_deltas
        if delta.key.scope is AccumulatorScope.BENEFIT_VISITS
    ]
    assert visit_deltas == [
        next(
            delta
            for delta in result.accumulator_deltas
            if delta.key.scope is AccumulatorScope.BENEFIT_VISITS
        )
    ]
    assert visit_deltas[0].quantity == 1
    assert visit_deltas[0].key == _visit_key()


def test_visit_limit_last_allowed_visit_is_approved() -> None:
    ctx = _ctx(accumulator_consumed={_visit_key(): 11})
    result = adjudicate(_claim(_line()), ctx)
    decision = result.line_results[0].decision
    assert decision is not None
    assert decision.outcome is LineOutcome.APPROVED
    assert ReasonCodeId.DEN_VISIT_LIMIT not in decision.reasons
    assert any(
        delta.key == _visit_key() and delta.quantity == 1
        for delta in result.accumulator_deltas
    )


def test_visit_limit_after_limit_denies_the_whole_line() -> None:
    ctx = _ctx(accumulator_consumed={_visit_key(): 12})
    result = adjudicate(_claim(_line()), ctx)
    decision = result.line_results[0].decision
    assert decision is not None
    assert decision.outcome is LineOutcome.DENIED
    assert ReasonCodeId.DEN_VISIT_LIMIT in decision.reasons
    assert decision.amounts is not None
    assert decision.amounts.plan_paid == Money.zero()
    assert decision.amounts.denied_amount == Money(4_000)
    assert decision.amounts.deductible_applied == Money.zero()
    decision.amounts.check_conservation(Money(4_000))
    assert result.accumulator_deltas == ()


def test_two_lines_share_remaining_dollar_limit_in_line_number_order() -> None:
    ctx = _ctx(
        plan=_plan(benefits=(_benefit(annual_limit_amount=Money(10_000)),)),
        accumulator_consumed={_amount_key(): 8_000},
    )
    claim = _claim(
        _line(
            id="line2",
            line_number=2,
            billed_amount=Money(4_000),
            service_date=date(2026, 3, 16),
        ),
        _line(id="line1", line_number=1, billed_amount=Money(4_000)),
    )
    result = adjudicate(claim, ctx)
    first, second = result.line_results
    assert first.line_id == "line1"
    assert second.line_id == "line2"
    assert first.decision is not None
    assert second.decision is not None
    assert first.decision.outcome is LineOutcome.PARTIALLY_APPROVED
    assert first.decision.amounts is not None
    assert first.decision.amounts.plan_paid == Money(2_000)
    assert first.decision.amounts.denied_amount == Money(2_000)
    assert second.decision.outcome is LineOutcome.DENIED
    assert second.decision.amounts is not None
    assert second.decision.amounts.plan_paid == Money.zero()
    assert second.decision.amounts.denied_amount == Money(4_000)
    total_paid = sum(
        delta.quantity
        for delta in result.accumulator_deltas
        if delta.key.scope is AccumulatorScope.BENEFIT_AMOUNT
    )
    assert total_paid == 2_000


def test_cross_benefit_deductible_is_shared_then_each_benefit_pays_its_own_limit() -> None:
    ctx = _ctx(
        plan=_plan(
            deductible=Money(1_000),
            benefits=(
                _benefit("PHYSIO", annual_limit_amount=Money(100_000)),
                _benefit("DIAGNOSTICS", annual_limit_amount=Money(100_000)),
            ),
        )
    )
    claim = _claim(
        _line(id="line1", line_number=1, billed_amount=Money(400)),
        _line(
            id="line2",
            line_number=2,
            service_code="DIAG-1",
            billed_amount=Money(800),
            diagnosis_code="R10.9",
        ),
    )
    result = adjudicate(claim, ctx)
    physio, diagnostics = result.line_results
    assert physio.deductible is not None
    assert diagnostics.deductible is not None
    assert physio.deductible.applied == Money(400)
    assert diagnostics.deductible.applied == Money(600)
    assert diagnostics.deductible.remaining_before == Money(600)
    assert physio.decision is not None
    assert diagnostics.decision is not None
    assert physio.decision.amounts is not None
    assert diagnostics.decision.amounts is not None
    assert physio.decision.amounts.plan_paid == Money.zero()
    assert diagnostics.decision.amounts.plan_paid == Money(200)
    deductible_total = sum(
        delta.quantity
        for delta in result.accumulator_deltas
        if delta.key.scope is AccumulatorScope.DEDUCTIBLE
    )
    assert deductible_total == 1_000
    assert all(
        delta.key.benefit_code is None
        for delta in result.accumulator_deltas
        if delta.key.scope is AccumulatorScope.DEDUCTIBLE
    )


def test_cross_plan_year_lines_use_separate_accumulator_keys() -> None:
    ctx = _ctx(
        policy=_policy(effective_date=date(2025, 1, 1)),
        as_of=date(2026, 3, 20),
        plan=_plan(
            deductible=Money(1_000),
            benefits=(_benefit(annual_limit_amount=Money(10_000)),),
        ),
        accumulator_consumed={
            _deductible_key(2025): 1_000,
            _amount_key(2025): 10_000,
        },
    )
    claim = _claim(
        _line(id="line1", line_number=1, service_date=date(2025, 12, 31)),
        _line(id="line2", line_number=2, service_date=date(2026, 1, 1)),
    )
    result = adjudicate(claim, ctx)
    prior_year, new_year = result.line_results
    assert prior_year.decision is not None
    assert new_year.decision is not None
    assert prior_year.decision.amounts is not None
    assert new_year.decision.amounts is not None
    assert prior_year.deductible is not None
    assert new_year.deductible is not None
    assert prior_year.deductible.applied == Money.zero()
    assert prior_year.decision.amounts.plan_paid == Money.zero()
    assert prior_year.decision.outcome is LineOutcome.DENIED
    assert new_year.deductible.applied == Money(1_000)
    assert new_year.decision.amounts.plan_paid == Money(3_000)
    assert new_year.decision.outcome is LineOutcome.APPROVED
    assert {delta.key.plan_year for delta in result.accumulator_deltas} == {2025, 2026}


def test_visit_denial_does_not_consume_deductible() -> None:
    ctx = _ctx(
        plan=_plan(
            deductible=Money(1_000),
            benefits=(
                _benefit("PHYSIO", annual_visit_limit=12),
                _benefit("DIAGNOSTICS", annual_visit_limit=12),
            ),
        ),
        accumulator_consumed={_visit_key(): 12},
    )
    claim = _claim(
        _line(id="line1", line_number=1),
        _line(
            id="line2",
            line_number=2,
            service_code="DIAG-1",
            billed_amount=Money(400),
            diagnosis_code="R10.9",
        ),
    )
    result = adjudicate(claim, ctx)
    physio, diagnostics = result.line_results
    assert physio.decision is not None
    assert physio.decision.reasons[-1] is ReasonCodeId.DEN_VISIT_LIMIT
    assert physio.deductible is None
    assert diagnostics.deductible is not None
    assert diagnostics.deductible.applied == Money(400)
    assert diagnostics.deductible.remaining_before == Money(1_000)
