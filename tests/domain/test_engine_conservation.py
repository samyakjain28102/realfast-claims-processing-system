"""Money conservation on every priced decision (D27). No Hypothesis in this project."""

from __future__ import annotations

import itertools
from datetime import date, datetime

from app.domain.accumulators import AccumulatorKey, AccumulatorScope
from app.domain.engine import AdjudicationContext, adjudicate
from app.domain.entities import Claim, ClaimLine, Plan, Policy, ServiceCatalogueEntry
from app.domain.money import Money
from app.domain.rules import Benefit


def _adjudicate(
    *,
    billed: int,
    scheduled: int,
    deductible: int,
    deductible_consumed: int,
    amount_limit: int | None,
    amount_consumed: int,
    visit_limit: int | None,
    visit_consumed: int,
):
    benefit = Benefit(
        code="PHYSIO",
        name="Physiotherapy",
        covered=True,
        excluded=False,
        annual_limit_amount=None if amount_limit is None else Money(amount_limit),
        annual_visit_limit=visit_limit,
    )
    consumed: dict[AccumulatorKey, int] = {}
    if deductible_consumed:
        consumed[
            AccumulatorKey("m1", 2026, AccumulatorScope.DEDUCTIBLE, None)
        ] = deductible_consumed
    if amount_consumed:
        consumed[
            AccumulatorKey("m1", 2026, AccumulatorScope.BENEFIT_AMOUNT, "PHYSIO")
        ] = amount_consumed
    if visit_consumed:
        consumed[
            AccumulatorKey("m1", 2026, AccumulatorScope.BENEFIT_VISITS, "PHYSIO")
        ] = visit_consumed
    ctx = AdjudicationContext(
        policy=Policy(
            id="pol1",
            member_id="m1",
            plan_id="plan1",
            effective_date=date(2026, 1, 1),
            termination_date=None,
        ),
        plan=Plan(
            id="plan1",
            version=3,
            deductible=Money(deductible),
            benefits=(benefit,),
        ),
        catalogue={
            "PHYSIO-30": ServiceCatalogueEntry(
                service_code="PHYSIO-30",
                description="Physio",
                benefit_code="PHYSIO",
                scheduled_amount=Money(scheduled),
            )
        },
        suspected_duplicate_keys=frozenset(),
        as_of=date(2026, 3, 20),
        decided_at=datetime(2026, 3, 20, 10, 0),
        accumulator_consumed=consumed,
    )
    claim = Claim(
        id="claim1",
        member_id="m1",
        submitted_at=datetime(2026, 3, 20, 9, 0),
        lines=(
            ClaimLine(
                id="line1",
                claim_id="claim1",
                line_number=1,
                provider_id="prov1",
                service_code="PHYSIO-30",
                service_date=date(2026, 3, 15),
                billed_amount=Money(billed),
                diagnosis_code="M54.5",
            ),
        ),
    )
    return adjudicate(claim, ctx)


def test_priced_decisions_conserve_money_across_limit_grid() -> None:
    billed_values = (0, 1_000, 4_000, 8_000)
    scheduled_values = (0, 2_000, 4_000)
    deductible_values = (0, 1_000, 5_000)
    deductible_consumed_values = (0, 1_000)
    amount_limits = (None, 1_000, 10_000)
    amount_consumed_values = (0, 500)
    visit_limits = (None, 0, 12)
    visit_consumed_values = (0, 12)

    priced = 0
    for combo in itertools.product(
        billed_values,
        scheduled_values,
        deductible_values,
        deductible_consumed_values,
        amount_limits,
        amount_consumed_values,
        visit_limits,
        visit_consumed_values,
    ):
        (
            billed,
            scheduled,
            deductible,
            deductible_consumed,
            amount_limit,
            amount_consumed,
            visit_limit,
            visit_consumed,
        ) = combo
        if deductible_consumed > deductible:
            continue
        if amount_limit is not None and amount_consumed > amount_limit:
            continue
        if visit_limit is not None and visit_consumed > visit_limit:
            continue
        result = _adjudicate(
            billed=billed,
            scheduled=scheduled,
            deductible=deductible,
            deductible_consumed=deductible_consumed,
            amount_limit=amount_limit,
            amount_consumed=amount_consumed,
            visit_limit=visit_limit,
            visit_consumed=visit_consumed,
        )
        decision = result.line_results[0].decision
        assert decision is not None
        if decision.amounts is None:
            continue
        decision.amounts.check_conservation(Money(billed))
        priced += 1
    assert priced > 100
