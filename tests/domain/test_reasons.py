from app.domain.reasons import (
    REASON_CATALOGUE,
    Liability,
    ReasonCategory,
    ReasonCodeId,
    get_reason,
)


def test_catalogue_contains_every_reason_code_id() -> None:
    assert set(REASON_CATALOGUE) == set(ReasonCodeId)


def test_hum_upheld_is_not_in_the_catalogue() -> None:
    assert not any(code.value == "HUM_UPHELD" for code in ReasonCodeId)


def test_deductible_and_above_allowed_are_not_appealable() -> None:
    assert get_reason(ReasonCodeId.MEM_DEDUCTIBLE).appealable is False
    assert get_reason(ReasonCodeId.MEM_ABOVE_ALLOWED).appealable is False


def test_denial_codes_are_appealable() -> None:
    denial_codes = (
        ReasonCodeId.DEN_NOT_ELIGIBLE,
        ReasonCodeId.DEN_NOT_COVERED,
        ReasonCodeId.DEN_EXCLUDED,
        ReasonCodeId.DEN_ANNUAL_LIMIT,
        ReasonCodeId.DEN_VISIT_LIMIT,
        ReasonCodeId.DEN_DUPLICATE,
    )
    for code in denial_codes:
        reason = get_reason(code)
        assert reason.appealable is True
        assert reason.category == ReasonCategory.DEN
        assert reason.liability == Liability.MEMBER


def test_review_and_reject_codes_have_no_liability_or_appealability() -> None:
    for code in (
        ReasonCodeId.REV_UNKNOWN_SERVICE,
        ReasonCodeId.REV_NO_PRICE,
        ReasonCodeId.REV_SUSPECTED_DUPLICATE,
        ReasonCodeId.REJ_INVALID_CLAIM,
    ):
        reason = get_reason(code)
        assert reason.liability is None
        assert reason.appealable is None


def test_info_covered_assigns_liability_to_plan() -> None:
    reason = get_reason(ReasonCodeId.INFO_COVERED)
    assert reason.category == ReasonCategory.INFO
    assert reason.liability == Liability.PLAN


def test_excluded_and_not_covered_are_distinct_codes() -> None:
    excluded = get_reason(ReasonCodeId.DEN_EXCLUDED)
    not_covered = get_reason(ReasonCodeId.DEN_NOT_COVERED)
    assert excluded.code != not_covered.code
    assert excluded.message != not_covered.message
