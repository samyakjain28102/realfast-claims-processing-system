"""Duplicate gates: confirmed in-claim deny, suspected cross-claim review."""

from __future__ import annotations

from datetime import date, datetime

from app.application.prior_duplicates import (
    PriorLineAnchor,
    suspected_duplicate_keys_from_prior,
)
from app.domain.accumulators import AccumulatorKey, AccumulatorScope
from app.domain.engine import AdjudicationContext, adjudicate, duplicate_identity
from app.domain.entities import Claim, ClaimLine, Plan, Policy, ServiceCatalogueEntry
from app.domain.money import Money
from app.domain.reasons import ReasonCodeId
from app.domain.rules import Benefit
from app.domain.states import LineOutcome, LineState


def _physio(*, visit_limit: int | None = 12, amount_limit: Money | None = Money(100_000)) -> Benefit:
    return Benefit(
        code="PHYSIO",
        name="Physiotherapy",
        covered=True,
        excluded=False,
        annual_limit_amount=amount_limit,
        annual_visit_limit=visit_limit,
    )


def _ctx(**overrides: object) -> AdjudicationContext:
    defaults: dict[str, object] = {
        "policy": Policy(
            id="pol1",
            member_id="m1",
            plan_id="plan1",
            effective_date=date(2026, 1, 1),
            termination_date=None,
        ),
        "plan": Plan(
            id="plan1",
            version=3,
            deductible=Money.zero(),
            benefits=(_physio(),),
        ),
        "catalogue": {
            "PHYSIO-30": ServiceCatalogueEntry(
                service_code="PHYSIO-30",
                description="Physio session",
                benefit_code="PHYSIO",
                scheduled_amount=Money(4_000),
            )
        },
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


def _claim(*lines: ClaimLine, claim_id: str = "claim1") -> Claim:
    remapped = tuple(
        ClaimLine(
            id=line.id,
            claim_id=claim_id,
            line_number=line.line_number,
            provider_id=line.provider_id,
            service_code=line.service_code,
            service_date=line.service_date,
            billed_amount=line.billed_amount,
            diagnosis_code=line.diagnosis_code,
        )
        for line in lines
    )
    return Claim(
        id=claim_id,
        member_id="m1",
        submitted_at=datetime(2026, 3, 20, 9, 0),
        lines=remapped,
    )


def test_duplicate_identity_excludes_billed_amount() -> None:
    key = duplicate_identity(
        member_id="m1",
        provider_id="prov1",
        service_code="PHYSIO-30",
        service_date=date(2026, 3, 15),
    )
    assert not hasattr(key, "billed_amount")


def test_exact_duplicate_within_claim_denies_second_line() -> None:
    claim = _claim(
        _line(id="line1", line_number=1),
        _line(id="line2", line_number=2, billed_amount=Money(4_000)),
    )
    result = adjudicate(claim, _ctx())
    first, second = result.line_results
    assert first.decision is not None
    assert first.decision.outcome is LineOutcome.APPROVED
    assert second.decision is not None
    assert second.decision.outcome is LineOutcome.DENIED
    assert second.decision.reasons == (ReasonCodeId.DEN_DUPLICATE,)
    assert ReasonCodeId.DEN_VISIT_LIMIT not in second.decision.reasons


def test_duplicate_against_prior_adjudicated_claim_is_suspected() -> None:
    prior_keys = suspected_duplicate_keys_from_prior(
        (
            PriorLineAnchor(
                member_id="m1",
                provider_id="prov1",
                service_code="PHYSIO-30",
                service_date=date(2026, 3, 15),
                line_state=LineState.APPROVED,
            ),
        )
    )
    claim = _claim(_line(), claim_id="claim2")
    result = adjudicate(claim, _ctx(suspected_duplicate_keys=prior_keys))
    decision = result.line_results[0].decision
    assert decision is not None
    assert decision.outcome is LineOutcome.NEEDS_REVIEW
    assert decision.reasons == (ReasonCodeId.REV_SUSPECTED_DUPLICATE,)
    assert result.accumulator_deltas == ()


def test_same_service_with_different_billed_amount_still_matches() -> None:
    prior_keys = suspected_duplicate_keys_from_prior(
        (
            PriorLineAnchor(
                member_id="m1",
                provider_id="prov1",
                service_code="PHYSIO-30",
                service_date=date(2026, 3, 15),
                line_state=LineState.DENIED,
            ),
        )
    )
    claim = _claim(_line(billed_amount=Money(9_999)), claim_id="claim2")
    result = adjudicate(claim, _ctx(suspected_duplicate_keys=prior_keys))
    decision = result.line_results[0].decision
    assert decision is not None
    assert decision.reasons == (ReasonCodeId.REV_SUSPECTED_DUPLICATE,)

    in_claim = _claim(
        _line(id="line1", line_number=1, billed_amount=Money(3_000)),
        _line(id="line2", line_number=2, billed_amount=Money(8_000)),
    )
    in_claim_result = adjudicate(in_claim, _ctx())
    assert in_claim_result.line_results[1].decision is not None
    assert in_claim_result.line_results[1].decision.reasons == (
        ReasonCodeId.DEN_DUPLICATE,
    )


def test_prior_unresolved_review_line_is_not_a_duplicate_anchor() -> None:
    prior_keys = suspected_duplicate_keys_from_prior(
        (
            PriorLineAnchor(
                member_id="m1",
                provider_id="prov1",
                service_code="PHYSIO-30",
                service_date=date(2026, 3, 15),
                line_state=LineState.NEEDS_REVIEW,
            ),
        )
    )
    assert prior_keys == frozenset()
    claim = _claim(_line(), claim_id="claim2")
    result = adjudicate(claim, _ctx(suspected_duplicate_keys=prior_keys))
    decision = result.line_results[0].decision
    assert decision is not None
    assert decision.outcome is LineOutcome.APPROVED
    assert ReasonCodeId.REV_SUSPECTED_DUPLICATE not in decision.reasons


def test_legitimate_repeated_service_on_a_different_date_is_not_a_duplicate() -> None:
    prior_keys = suspected_duplicate_keys_from_prior(
        (
            PriorLineAnchor(
                member_id="m1",
                provider_id="prov1",
                service_code="PHYSIO-30",
                service_date=date(2026, 3, 14),
                line_state=LineState.APPROVED,
            ),
        )
    )
    claim = _claim(_line(service_date=date(2026, 3, 15)), claim_id="claim2")
    result = adjudicate(claim, _ctx(suspected_duplicate_keys=prior_keys))
    decision = result.line_results[0].decision
    assert decision is not None
    assert decision.outcome is LineOutcome.APPROVED
    assert ReasonCodeId.REV_SUSPECTED_DUPLICATE not in decision.reasons
    assert ReasonCodeId.DEN_DUPLICATE not in decision.reasons


def test_confirmed_duplicate_does_not_consume_the_final_visit_or_benefit_amount() -> None:
    visit_key = AccumulatorKey("m1", 2026, AccumulatorScope.BENEFIT_VISITS, "PHYSIO")
    amount_key = AccumulatorKey("m1", 2026, AccumulatorScope.BENEFIT_AMOUNT, "PHYSIO")
    ctx = _ctx(
        plan=Plan(
            id="plan1",
            version=3,
            deductible=Money.zero(),
            benefits=(_physio(visit_limit=12, amount_limit=Money(10_000)),),
        ),
        accumulator_consumed={visit_key: 11, amount_key: 6_000},
    )
    claim = _claim(
        _line(id="line1", line_number=1),
        _line(id="line2", line_number=2),
    )
    result = adjudicate(claim, ctx)
    first, second = result.line_results
    assert first.decision is not None
    assert first.decision.outcome is LineOutcome.APPROVED
    assert first.decision.amounts is not None
    assert first.decision.amounts.plan_paid == Money(4_000)
    assert second.decision is not None
    assert second.decision.reasons == (ReasonCodeId.DEN_DUPLICATE,)
    assert second.decision.amounts is None
    assert [delta.key.scope for delta in result.accumulator_deltas] == [
        AccumulatorScope.BENEFIT_AMOUNT,
        AccumulatorScope.BENEFIT_VISITS,
    ]
    assert sum(
        delta.quantity
        for delta in result.accumulator_deltas
        if delta.key.scope is AccumulatorScope.BENEFIT_VISITS
    ) == 1
    assert sum(
        delta.quantity
        for delta in result.accumulator_deltas
        if delta.key.scope is AccumulatorScope.BENEFIT_AMOUNT
    ) == 4_000
