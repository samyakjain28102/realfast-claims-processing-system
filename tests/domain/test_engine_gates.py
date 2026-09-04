"""Gates 0–6: structural validation through coverage and exclusion."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.domain.engine import (
    AdjudicationContext,
    SuspectedDuplicateKey,
    adjudicate,
)
from app.domain.entities import Claim, ClaimLine
from app.domain.money import Money
from app.domain.reasons import ReasonCodeId
from app.domain.rules import Benefit
from app.domain.entities import Plan, Policy, ServiceCatalogueEntry
from app.domain.states import LineOutcome


def _physio_benefit(*, covered: bool = True, excluded: bool = False) -> Benefit:
    return Benefit(
        code="PHYSIO",
        name="Physiotherapy",
        covered=covered,
        excluded=excluded,
        annual_limit_amount=Money(100_000),
        annual_visit_limit=12,
    )


def _cosmetic_benefit() -> Benefit:
    return Benefit(
        code="COSMETIC",
        name="Cosmetic",
        covered=True,
        excluded=True,
        annual_limit_amount=None,
        annual_visit_limit=None,
    )


def _plan(*benefits: Benefit) -> Plan:
    return Plan(
        id="plan1",
        version=3,
        deductible=Money.zero(),
        benefits=benefits,
    )


def _policy(**overrides: object) -> Policy:
    defaults = {
        "id": "pol1",
        "member_id": "m1",
        "plan_id": "plan1",
        "effective_date": date(2026, 1, 1),
        "termination_date": None,
    }
    defaults.update(overrides)
    return Policy(**defaults)  # type: ignore[arg-type]


def _catalogue() -> dict[str, ServiceCatalogueEntry]:
    return {
        "PHYSIO-30": ServiceCatalogueEntry(
            service_code="PHYSIO-30",
            description="Physio session",
            benefit_code="PHYSIO",
            scheduled_amount=Money(4_000),
        ),
        "COSMETIC-1": ServiceCatalogueEntry(
            service_code="COSMETIC-1",
            description="Cosmetic procedure",
            benefit_code="COSMETIC",
            scheduled_amount=Money(10_000),
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


def _decision_for_line(result, line_id: str):
    for line_result in result.line_results:
        if line_result.line_id == line_id:
            return line_result.decision
    raise AssertionError(f"no result for line {line_id}")


# --- Gate 0 ---


def test_empty_claim_is_rejected_with_no_line_decisions() -> None:
    result = adjudicate(_claim(), _ctx())
    assert result.rejected is True
    assert result.rejection_reason is ReasonCodeId.REJ_INVALID_CLAIM
    assert result.line_results == ()


def test_future_service_date_rejects_entire_claim() -> None:
    claim = _claim(_line(service_date=date(2026, 4, 1)))
    result = adjudicate(claim, _ctx(as_of=date(2026, 3, 20)))
    assert result.rejected is True
    assert result.rejection_reason is ReasonCodeId.REJ_INVALID_CLAIM


def test_line_claim_id_mismatch_rejects_claim() -> None:
    claim = _claim(_line(claim_id="other-claim"))
    result = adjudicate(claim, _ctx())
    assert result.rejected is True


def test_policy_plan_mismatch_rejects_claim_with_no_line_decisions() -> None:
    claim = _claim(_line())
    result = adjudicate(
        claim,
        _ctx(policy=_policy(plan_id="other-plan")),
    )
    assert result.rejected is True
    assert result.rejection_reason is ReasonCodeId.REJ_INVALID_CLAIM
    assert result.line_results == ()


# --- Gate 1 ---


def test_unknown_service_routes_to_needs_review() -> None:
    claim = _claim(_line(service_code="UNKNOWN"))
    result = adjudicate(claim, _ctx())
    decision = _decision_for_line(result, "line1")
    assert decision is not None
    assert decision.outcome is LineOutcome.NEEDS_REVIEW
    assert decision.reasons == (ReasonCodeId.REV_UNKNOWN_SERVICE,)
    assert decision.amounts is None


# --- Gate 2 ---


def test_confirmed_duplicate_denies_second_line_only() -> None:
    claim = _claim(
        _line(id="line1", line_number=1),
        _line(
            id="line2",
            line_number=2,
            service_code="PHYSIO-30",
            service_date=date(2026, 3, 15),
            provider_id="prov1",
            billed_amount=Money(6_000),
        ),
    )
    result = adjudicate(claim, _ctx())
    line1 = next(r for r in result.line_results if r.line_id == "line1")
    line2 = next(r for r in result.line_results if r.line_id == "line2")
    assert line1.decision is not None
    assert line1.decision.outcome is LineOutcome.APPROVED
    assert line2.decision is not None
    assert line2.decision.outcome is LineOutcome.DENIED
    assert line2.decision.reasons == (ReasonCodeId.DEN_DUPLICATE,)


# --- Gate 3 ---


def test_suspected_duplicate_routes_to_needs_review() -> None:
    key = SuspectedDuplicateKey("m1", "prov1", "PHYSIO-30", date(2026, 3, 15))
    claim = _claim(_line())
    result = adjudicate(claim, _ctx(suspected_duplicate_keys=frozenset({key})))
    decision = _decision_for_line(result, "line1")
    assert decision is not None
    assert decision.outcome is LineOutcome.NEEDS_REVIEW
    assert decision.reasons == (ReasonCodeId.REV_SUSPECTED_DUPLICATE,)


def test_suspected_duplicate_key_ignores_billed_amount_d17() -> None:
    """D17: duplicate key is member + provider + service + date; billed amount excluded."""
    key = SuspectedDuplicateKey("m1", "prov1", "PHYSIO-30", date(2026, 3, 15))
    claim = _claim(_line(billed_amount=Money(9_999)))
    result = adjudicate(claim, _ctx(suspected_duplicate_keys=frozenset({key})))
    decision = _decision_for_line(result, "line1")
    assert decision is not None
    assert decision.reasons == (ReasonCodeId.REV_SUSPECTED_DUPLICATE,)


def test_no_suspected_duplicate_keys_clears_line() -> None:
    claim = _claim(_line(billed_amount=Money(9_999)))
    result = adjudicate(claim, _ctx(suspected_duplicate_keys=frozenset()))
    assert result.line_results[0].decision is not None
    assert result.line_results[0].decision.outcome is LineOutcome.APPROVED


# --- Gate 4 ---


def test_ineligible_service_date_is_denied() -> None:
    claim = _claim(_line(service_date=date(2025, 12, 31)))
    result = adjudicate(
        claim,
        _ctx(policy=_policy(effective_date=date(2026, 1, 1))),
    )
    decision = _decision_for_line(result, "line1")
    assert decision is not None
    assert decision.outcome is LineOutcome.DENIED
    assert decision.reasons == (ReasonCodeId.DEN_NOT_ELIGIBLE,)


def test_policy_termination_mid_claim_denies_line_after_termination_date() -> None:
    """Per-line eligibility gate: service after termination_date is denied."""
    claim = _claim(
        _line(id="line1", line_number=1, service_date=date(2026, 3, 15)),
        _line(
            id="line2",
            line_number=2,
            service_code="PHYSIO-30",
            service_date=date(2026, 3, 17),
            provider_id="prov1",
            billed_amount=Money(5_000),
        ),
    )
    result = adjudicate(
        claim,
        _ctx(policy=_policy(termination_date=date(2026, 3, 16))),
    )
    line1 = _decision_for_line(result, "line1")
    line2 = _decision_for_line(result, "line2")
    assert line1 is not None
    assert line2 is not None
    assert line1.outcome is LineOutcome.APPROVED
    assert line2.outcome is LineOutcome.DENIED
    assert line2.reasons == (ReasonCodeId.DEN_NOT_ELIGIBLE,)


# --- Gates 5 & 6 ---


def test_mapped_covered_benefit_passes_gate_5() -> None:
    claim = _claim(_line())
    result = adjudicate(claim, _ctx())
    line_result = result.line_results[0]
    assert line_result.decision is not None
    assert line_result.decision.outcome is LineOutcome.APPROVED
    assert ReasonCodeId.DEN_NOT_COVERED not in line_result.decision.reasons


def test_unmapped_benefit_routes_to_needs_review() -> None:
    claim = _claim(_line())
    result = adjudicate(claim, _ctx(plan=_plan()))
    decision = _decision_for_line(result, "line1")
    assert decision is not None
    assert decision.outcome is LineOutcome.NEEDS_REVIEW
    assert decision.reasons == (ReasonCodeId.REV_UNKNOWN_BENEFIT,)
    assert decision.amounts is None


def test_not_covered_benefit_is_denied_before_exclusion() -> None:
    plan = _plan(
        Benefit(
            code="PHYSIO",
            name="Physio",
            covered=False,
            excluded=False,
            annual_limit_amount=None,
            annual_visit_limit=None,
        )
    )
    claim = _claim(_line())
    result = adjudicate(claim, _ctx(plan=plan))
    decision = _decision_for_line(result, "line1")
    assert decision is not None
    assert decision.outcome is LineOutcome.DENIED
    assert decision.reasons == (ReasonCodeId.DEN_NOT_COVERED,)


def test_excluded_benefit_is_denied_with_distinct_reason() -> None:
    plan = _plan(_cosmetic_benefit())
    claim = _claim(_line(service_code="COSMETIC-1"))
    result = adjudicate(claim, _ctx(plan=plan))
    decision = _decision_for_line(result, "line1")
    assert decision is not None
    assert decision.outcome is LineOutcome.DENIED
    assert decision.reasons == (ReasonCodeId.DEN_EXCLUDED,)


def test_line_passing_gates_0_through_6_is_cleared_for_pricing() -> None:
    claim = _claim(_line())
    result = adjudicate(claim, _ctx())
    line_result = result.line_results[0]
    assert line_result.decision is not None
    assert line_result.decision.outcome is LineOutcome.APPROVED
    assert ReasonCodeId.DEN_NOT_COVERED not in line_result.decision.reasons


def test_unknown_service_stops_before_confirmed_duplicate_check() -> None:
    claim = _claim(
        _line(id="line1", line_number=1, service_code="UNKNOWN"),
        _line(
            id="line2",
            line_number=2,
            service_code="UNKNOWN",
            provider_id="prov1",
            service_date=date(2026, 3, 15),
        ),
    )
    result = adjudicate(claim, _ctx())
    second = _decision_for_line(result, "line2")
    assert second is not None
    assert second.reasons == (ReasonCodeId.REV_UNKNOWN_SERVICE,)
    assert ReasonCodeId.DEN_DUPLICATE not in second.reasons


def test_adjudication_is_deterministic() -> None:
    claim = _claim(_line())
    ctx = _ctx()
    first = adjudicate(claim, ctx)
    second = adjudicate(claim, ctx)
    assert first == second
