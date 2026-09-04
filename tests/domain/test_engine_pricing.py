"""Gate 7: fee-schedule pricing — allowed and above_allowed only."""

from __future__ import annotations

from datetime import date, datetime

from app.domain.engine import AdjudicationContext, adjudicate
from app.domain.entities import Claim, ClaimLine, Plan, Policy, ServiceCatalogueEntry
from app.domain.money import Money
from app.domain.reasons import ReasonCodeId
from app.domain.rules import Benefit
from app.domain.states import LineOutcome


def _physio_benefit() -> Benefit:
    return Benefit(
        code="PHYSIO",
        name="Physiotherapy",
        covered=True,
        excluded=False,
        annual_limit_amount=Money(100_000),
        annual_visit_limit=12,
    )


def _plan(*benefits: Benefit) -> Plan:
    return Plan(
        id="plan1",
        version=3,
        deductible=Money.zero(),
        benefits=benefits,
    )


def _policy() -> Policy:
    return Policy(
        id="pol1",
        member_id="m1",
        plan_id="plan1",
        effective_date=date(2026, 1, 1),
        termination_date=None,
    )


def _catalogue(*, scheduled_amount: Money | None = Money(4_000)) -> dict[str, ServiceCatalogueEntry]:
    return {
        "PHYSIO-30": ServiceCatalogueEntry(
            service_code="PHYSIO-30",
            description="Physio session",
            benefit_code="PHYSIO",
            scheduled_amount=scheduled_amount,
        ),
    }


def _ctx(**overrides: object) -> AdjudicationContext:
    defaults = {
        "policy": _policy(),
        "plan": _plan(_physio_benefit()),
        "catalogue": _catalogue(),
        "suspected_duplicate_keys": frozenset(),
        "as_of": date(2026, 3, 20),
        "decided_at": datetime(2026, 3, 20, 10, 0),
        "decided_by": "rules",
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
        "billed_amount": Money(5_000),
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


def test_billed_below_scheduled_allows_billed_amount() -> None:
    claim = _claim(_line(billed_amount=Money(3_000)))
    result = adjudicate(claim, _ctx())
    line_result = result.line_results[0]
    assert line_result.pricing is not None
    assert line_result.decision is not None
    assert line_result.decision.amounts is not None
    assert line_result.decision.amounts.allowed == Money(3_000)
    assert line_result.pricing.allowed == Money(3_000)
    assert line_result.pricing.above_allowed == Money.zero()
    assert line_result.pricing.scheduled_amount == Money(4_000)
    assert line_result.pricing.trace.step == "pricing"
    assert line_result.pricing.trace.result == "pass"


def test_billed_equal_to_scheduled_has_zero_above_allowed() -> None:
    claim = _claim(_line(billed_amount=Money(4_000)))
    result = adjudicate(claim, _ctx())
    pricing = result.line_results[0].pricing
    assert pricing is not None
    assert pricing.allowed == Money(4_000)
    assert pricing.above_allowed == Money.zero()
    assert pricing.trace.step == "pricing"
    assert pricing.trace.result == "pass"


def test_billed_above_scheduled_caps_allowed_at_schedule() -> None:
    claim = _claim(_line(billed_amount=Money(5_000)))
    result = adjudicate(claim, _ctx())
    pricing = result.line_results[0].pricing
    assert pricing is not None
    assert pricing.allowed == Money(4_000)
    assert pricing.above_allowed == Money(1_000)
    assert pricing.trace.step == "pricing"
    assert pricing.trace.inputs["billed_amount"] == 5_000
    assert pricing.trace.inputs["scheduled_amount"] == 4_000
    assert pricing.trace.inputs["allowed"] == 4_000
    assert pricing.trace.inputs["above_allowed"] == 1_000
    assert pricing.trace.result == "pass"


def test_missing_schedule_routes_to_needs_review() -> None:
    ctx = _ctx(catalogue=_catalogue(scheduled_amount=None))
    assert ctx.scheduled_amount_for("PHYSIO-30") is None
    claim = _claim(_line())
    result = adjudicate(claim, ctx)
    line_result = result.line_results[0]
    assert line_result.cleared_for_pricing is False
    assert line_result.pricing is None
    decision = line_result.decision
    assert decision is not None
    assert decision.outcome is LineOutcome.NEEDS_REVIEW
    assert decision.reasons == (ReasonCodeId.REV_NO_PRICE,)
    assert decision.amounts is None
    assert decision.trace[-1].step == "pricing"
    assert decision.trace[-1].result == "no_price"


def test_zero_billed_amount_prices_to_zero() -> None:
    """Zero billed is a pricing input, not a structural rejection."""
    claim = _claim(_line(billed_amount=Money.zero()))
    result = adjudicate(claim, _ctx())
    line_result = result.line_results[0]
    assert line_result.pricing is not None
    assert line_result.pricing.allowed == Money.zero()
    assert line_result.pricing.above_allowed == Money.zero()
    assert line_result.pricing.trace.result == "pass"
    assert line_result.decision is not None
    assert line_result.decision.amounts is not None
    line_result.decision.amounts.check_conservation(Money.zero())
