"""Deductible stage: shared policy-year accumulator, not a benefit dollar limit."""

from __future__ import annotations

from datetime import date, datetime

from app.domain.accumulators import AccumulatorKey, AccumulatorScope
from app.domain.engine import AdjudicationContext, adjudicate
from app.domain.entities import Claim, ClaimLine, Plan, Policy, ServiceCatalogueEntry
from app.domain.money import Money
from app.domain.reasons import ReasonCodeId
from app.domain.rules import Benefit
from app.domain.states import LineOutcome


def _benefit(code: str, name: str) -> Benefit:
    return Benefit(
        code=code,
        name=name,
        covered=True,
        excluded=False,
        annual_limit_amount=Money(100_000),
        annual_visit_limit=12,
    )


def _plan(*, deductible: Money, benefits: tuple[Benefit, ...]) -> Plan:
    return Plan(id="plan1", version=3, deductible=deductible, benefits=benefits)


def _policy() -> Policy:
    return Policy(
        id="pol1",
        member_id="m1",
        plan_id="plan1",
        effective_date=date(2026, 1, 1),
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
            scheduled_amount=Money(4_000),
        ),
    }


def _ctx(**overrides: object) -> AdjudicationContext:
    defaults: dict[str, object] = {
        "policy": _policy(),
        "plan": _plan(
            deductible=Money(10_000),
            benefits=(_benefit("PHYSIO", "Physiotherapy"),),
        ),
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


def _deductible_key() -> AccumulatorKey:
    return AccumulatorKey(
        member_id="m1",
        plan_year=2026,
        scope=AccumulatorScope.DEDUCTIBLE,
        benefit_code=None,
    )


def test_deductible_fully_unmet_applies_none_of_allowed() -> None:
    ctx = _ctx(accumulator_consumed={_deductible_key(): 10_000})
    result = adjudicate(_claim(_line()), ctx)
    line_result = result.line_results[0]
    assert line_result.decision is None
    assert line_result.deductible is not None
    assert line_result.deductible.applied == Money.zero()
    assert line_result.deductible.after_deductible == Money(4_000)
    assert line_result.deductible.trace.result == "met"
    assert result.accumulator_deltas == ()


def test_deductible_partially_consumed_leaves_remainder_for_later_gates() -> None:
    ctx = _ctx(plan=_plan(
        deductible=Money(1_000),
        benefits=(_benefit("PHYSIO", "Physiotherapy"),),
    ))
    result = adjudicate(_claim(_line(billed_amount=Money(4_000))), ctx)
    line_result = result.line_results[0]
    assert line_result.decision is None
    assert line_result.deductible is not None
    assert line_result.deductible.applied == Money(1_000)
    assert line_result.deductible.after_deductible == Money(3_000)
    assert line_result.deductible.trace.result == "partial"
    assert result.accumulator_deltas == ()


def test_deductible_fully_absorbs_allowed_amount() -> None:
    result = adjudicate(_claim(_line()), _ctx())
    line_result = result.line_results[0]
    decision = line_result.decision
    assert decision is not None
    assert decision.outcome is LineOutcome.APPROVED
    assert ReasonCodeId.MEM_DEDUCTIBLE in decision.reasons
    assert decision.amounts is not None
    assert decision.amounts.deductible_applied == Money(4_000)
    assert decision.amounts.plan_paid == Money.zero()
    assert decision.amounts.denied_amount == Money.zero()
    decision.amounts.check_conservation(Money(4_000))
    assert line_result.deductible is not None
    assert line_result.deductible.trace.result == "absorbed"
    assert line_result.deductible.trace.accumulator_before == 0
    assert line_result.deductible.trace.accumulator_after == 4_000
    assert len(result.accumulator_deltas) == 1
    assert result.accumulator_deltas[0].key == _deductible_key()
    assert result.accumulator_deltas[0].quantity == 4_000


def test_deductible_is_shared_across_benefits() -> None:
    ctx = _ctx(
        plan=_plan(
            deductible=Money(1_000),
            benefits=(
                _benefit("PHYSIO", "Physiotherapy"),
                _benefit("DIAGNOSTICS", "Diagnostics"),
            ),
        )
    )
    claim = _claim(
        _line(id="line1", line_number=1, billed_amount=Money(400)),
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
    assert physio.deductible is not None
    assert diagnostics.deductible is not None
    assert physio.deductible.applied == Money(400)
    assert diagnostics.deductible.applied == Money(400)
    assert diagnostics.deductible.remaining_before == Money(600)
    assert diagnostics.deductible.remaining_after == Money(200)
    assert all(delta.key.benefit_code is None for delta in result.accumulator_deltas)
    assert all(
        delta.key.scope is AccumulatorScope.DEDUCTIBLE
        for delta in result.accumulator_deltas
    )
    assert sum(delta.quantity for delta in result.accumulator_deltas) == 800


def test_deductible_does_not_consume_benefit_dollar_limit() -> None:
    benefit_key = AccumulatorKey(
        member_id="m1",
        plan_year=2026,
        scope=AccumulatorScope.BENEFIT_AMOUNT,
        benefit_code="PHYSIO",
    )
    ctx = _ctx(accumulator_consumed={benefit_key: 50_000})
    result = adjudicate(_claim(_line()), ctx)
    assert result.line_results[0].decision is not None
    assert result.line_results[0].decision.amounts is not None
    assert result.line_results[0].decision.amounts.plan_paid == Money.zero()
    assert [delta.key.scope for delta in result.accumulator_deltas] == [
        AccumulatorScope.DEDUCTIBLE
    ]
    assert benefit_key not in {delta.key for delta in result.accumulator_deltas}
    assert ctx.accumulator_consumed[benefit_key] == 50_000


def test_needs_review_posts_no_accumulator_deltas() -> None:
    result = adjudicate(_claim(_line(service_code="UNKNOWN")), _ctx())
    assert result.line_results[0].decision is not None
    assert result.line_results[0].decision.outcome is LineOutcome.NEEDS_REVIEW
    assert result.accumulator_deltas == ()
