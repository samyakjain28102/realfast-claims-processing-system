"""Claim extraction: Gemini → Pydantic → canonical Claim. Gemini is mocked."""

from __future__ import annotations

import ast
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.claim_extractor import (
    EXTRACTION_JSON_SCHEMA,
    ClaimExtractionApiError,
    ClaimExtractionValidationError,
    parse_extracted_facts,
    to_canonical_claim,
)
from app.domain.engine import AdjudicationContext, adjudicate
from app.domain.entities import Claim, ClaimLine, Plan, Policy, ServiceCatalogueEntry
from app.domain.money import Money
from app.domain.rules import Benefit
from app.infrastructure.gemini_extractor import DEFAULT_GEMINI_MODEL, GeminiClaimExtractor


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "member_id": "m1",
        "lines": [
            {
                "line_number": 1,
                "provider_id": "prov1",
                "service_code": "PHYSIO-30",
                "service_date": "2026-03-15",
                "billed_amount_minor_units": 5_000,
                "diagnosis_code": "M54.5",
            }
        ],
    }
    payload.update(overrides)
    return payload


class _FakeModels:
    def __init__(self, *, text: str | None = None, error: Exception | None = None) -> None:
        self._text = text
        self._error = error
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return SimpleNamespace(text=self._text)


class _FakeClient:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models


def _extractor(models: _FakeModels) -> GeminiClaimExtractor:
    return GeminiClaimExtractor(client=_FakeClient(models))


def _claim_ids() -> tuple[str, datetime]:
    return "claim1", datetime(2026, 3, 20, 9, 0)


def test_valid_structured_gemini_response_becomes_canonical_claim() -> None:
    models = _FakeModels(text=json.dumps(_valid_payload()))
    claim_id, submitted_at = _claim_ids()
    claim = _extractor(models).extract(
        "member m1 physio at prov1",
        claim_id=claim_id,
        submitted_at=submitted_at,
    )

    assert isinstance(claim, Claim)
    assert claim.id == "claim1"
    assert claim.member_id == "m1"
    assert claim.submitted_at == submitted_at
    assert len(claim.lines) == 1
    line = claim.lines[0]
    assert isinstance(line, ClaimLine)
    assert line.id == "claim1-L1"
    assert line.claim_id == "claim1"
    assert line.line_number == 1
    assert line.provider_id == "prov1"
    assert line.service_code == "PHYSIO-30"
    assert line.service_date == date(2026, 3, 15)
    assert line.billed_amount == Money(5_000)
    assert line.diagnosis_code == "M54.5"
    assert not hasattr(line, "quantity")
    assert not hasattr(claim, "outcome")

    call = models.calls[0]
    assert call["model"] == DEFAULT_GEMINI_MODEL
    config = call["config"]
    assert isinstance(config, dict)
    assert config["response_mime_type"] == "application/json"
    assert config["response_json_schema"] == EXTRACTION_JSON_SCHEMA
    assert "outcome" not in EXTRACTION_JSON_SCHEMA["properties"]


def test_malformed_gemini_response_is_validation_failure() -> None:
    models = _FakeModels(text="{not-json")
    claim_id, submitted_at = _claim_ids()
    with pytest.raises(ClaimExtractionValidationError, match="malformed"):
        _extractor(models).extract("a claim", claim_id=claim_id, submitted_at=submitted_at)


def test_missing_required_field_is_validation_failure() -> None:
    payload = _valid_payload()
    del payload["member_id"]
    models = _FakeModels(text=json.dumps(payload))
    claim_id, submitted_at = _claim_ids()
    with pytest.raises(ClaimExtractionValidationError, match="schema validation"):
        _extractor(models).extract("a claim", claim_id=claim_id, submitted_at=submitted_at)


def test_invalid_field_type_is_validation_failure() -> None:
    payload = _valid_payload()
    lines = payload["lines"]
    assert isinstance(lines, list)
    lines[0]["billed_amount_minor_units"] = "five thousand"
    models = _FakeModels(text=json.dumps(payload))
    claim_id, submitted_at = _claim_ids()
    with pytest.raises(ClaimExtractionValidationError, match="schema validation"):
        _extractor(models).extract("a claim", claim_id=claim_id, submitted_at=submitted_at)


def test_gemini_api_failure_is_api_error() -> None:
    models = _FakeModels(error=RuntimeError("unavailable"))
    claim_id, submitted_at = _claim_ids()
    with pytest.raises(ClaimExtractionApiError, match="Gemini request failed") as exc_info:
        _extractor(models).extract("a claim", claim_id=claim_id, submitted_at=submitted_at)
    assert "sk-" not in str(exc_info.value)
    assert "AIza" not in str(exc_info.value)


def test_missing_api_key_without_injected_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ClaimExtractionApiError, match="GEMINI_API_KEY is not set"):
        GeminiClaimExtractor()


def test_adjudication_fields_in_extraction_are_rejected() -> None:
    payload = _valid_payload(outcome="APPROVED", plan_paid=4000)
    with pytest.raises(ClaimExtractionValidationError, match="adjudication"):
        parse_extracted_facts(payload)


def test_quantity_is_ignored_because_domain_has_no_units() -> None:
    payload = _valid_payload()
    lines = payload["lines"]
    assert isinstance(lines, list)
    lines[0]["quantity"] = 3
    facts = parse_extracted_facts(payload)
    claim = to_canonical_claim(
        facts,
        claim_id="claim1",
        submitted_at=datetime(2026, 3, 20, 9, 0),
    )
    assert not hasattr(claim.lines[0], "quantity")


def test_empty_gemini_output_is_validation_failure() -> None:
    models = _FakeModels(text="   ")
    claim_id, submitted_at = _claim_ids()
    with pytest.raises(ClaimExtractionValidationError, match="empty"):
        _extractor(models).extract("a claim", claim_id=claim_id, submitted_at=submitted_at)


def test_domain_source_does_not_depend_on_gemini() -> None:
    domain_root = Path(__file__).resolve().parents[2] / "app" / "domain"
    forbidden = ("google.genai", "google.generativeai", "GEMINI_API_KEY", "GeminiClaimExtractor")
    for path in domain_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("google"), path
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("google"), path
                assert not node.module.startswith("app.infrastructure"), path
                assert not node.module.startswith("app.application"), path
        for token in forbidden:
            assert token not in source, f"{path} contains {token}"


def test_adjudicate_does_not_require_gemini_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
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
                billed_amount=Money(5_000),
                diagnosis_code="M54.5",
            ),
        ),
    )
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
            deductible=Money(50_000),
            benefits=(
                Benefit(
                    code="PHYSIO",
                    name="Physiotherapy",
                    covered=True,
                    excluded=False,
                    annual_limit_amount=Money(100_000),
                    annual_visit_limit=12,
                ),
            ),
        ),
        catalogue={
            "PHYSIO-30": ServiceCatalogueEntry(
                service_code="PHYSIO-30",
                description="Physio session",
                benefit_code="PHYSIO",
                scheduled_amount=Money(4_000),
            )
        },
        suspected_duplicate_keys=frozenset(),
        as_of=date(2026, 3, 20),
        decided_at=datetime(2026, 3, 20, 10, 0),
    )
    result = adjudicate(claim, ctx)
    assert result.rejected is False
    assert result.line_results[0].cleared_for_pricing is True
