"""Gemini-backed claim extractor. Domain must never import this module."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from google import genai

from app.application.claim_extractor import (
    EXTRACTION_JSON_SCHEMA,
    ClaimExtractionApiError,
    ClaimExtractionError,
    ClaimExtractionValidationError,
    ExtractedClaimFacts,
    parse_extracted_facts,
    to_canonical_claim,
)
from app.domain.entities import Claim

# [PROPOSED] Default model for structured extraction. Override via constructor.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

_API_KEY_ENV = "GEMINI_API_KEY"

_EXTRACT_INSTRUCTIONS = (
    "Extract claim facts from the unstructured text. "
    "Fill only member_id and line items: line_number, provider_id, service_code, "
    "service_date (YYYY-MM-DD), billed_amount_minor_units (integer minor units), "
    "diagnosis_code. "
    "If a required fact is not clearly present, omit it; do not guess or invent values. "
    "Do not decide coverage, pricing, deductible, limits, payment, outcome, or reason codes. "
    "Do not include explanations."
)


class GeminiClaimExtractor:
    """Infrastructure adapter: unstructured text → Gemini JSON → validated Claim."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        model: str = DEFAULT_GEMINI_MODEL,
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._client = client if client is not None else _build_client(api_key)

    def extract(
        self,
        unstructured_text: str,
        *,
        claim_id: str,
        submitted_at: datetime,
    ) -> Claim:
        facts = self.extract_facts(unstructured_text)
        return to_canonical_claim(facts, claim_id=claim_id, submitted_at=submitted_at)

    def extract_facts(self, unstructured_text: str) -> ExtractedClaimFacts:
        if not unstructured_text or not unstructured_text.strip():
            raise ClaimExtractionValidationError("unstructured text is empty")
        payload = self._generate_json_payload(unstructured_text)
        return parse_extracted_facts(payload)

    def _generate_json_payload(self, unstructured_text: str) -> object:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=_extraction_contents(unstructured_text),
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": EXTRACTION_JSON_SCHEMA,
                    "temperature": 0,
                },
            )
        except ClaimExtractionError:
            raise
        except Exception as exc:
            raise ClaimExtractionApiError("Gemini request failed") from exc

        raw = getattr(response, "text", None)
        if not raw or not str(raw).strip():
            raise ClaimExtractionValidationError("Gemini returned empty output")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ClaimExtractionValidationError("malformed Gemini output") from exc


def _build_client(api_key: str | None) -> Any:
    key = api_key if api_key is not None else os.environ.get(_API_KEY_ENV)
    if not key:
        raise ClaimExtractionApiError("GEMINI_API_KEY is not set")
    try:
        return genai.Client(api_key=key)
    except Exception as exc:
        raise ClaimExtractionApiError("Gemini client could not be created") from exc


def _extraction_contents(unstructured_text: str) -> str:
    return f"{_EXTRACT_INSTRUCTIONS}\n\nUnstructured claim:\n{unstructured_text}"
