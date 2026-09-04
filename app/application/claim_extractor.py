"""Claim fact extraction port — Gemini-free. Maps validated facts to canonical Claim."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator

from app.domain.entities import Claim, ClaimLine
from app.domain.money import Money

# Hallucinated adjudication fields must fail closed (D30). Unknown extra keys such as
# quantity are ignored — ClaimLine has no units field (D11).
_ADJUDICATION_FIELD_NAMES = frozenset(
    {
        "outcome",
        "approval",
        "denial",
        "approved",
        "denied",
        "allowed",
        "allowed_amount",
        "above_allowed",
        "deductible",
        "deductible_applied",
        "plan_paid",
        "denied_amount",
        "reason",
        "reason_code",
        "reason_codes",
        "reasons",
        "explanation",
        "trace",
        "benefit_limit",
        "annual_limit",
        "visit_limit",
        "coverage",
        "covered",
        "excluded",
    }
)

# JSON Schema sent to Gemini structured output. Keep this the source for the API
# contract; Pydantic below is the validator. [PROPOSED] schema shape.
EXTRACTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "member_id": {"type": "string"},
        "lines": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "line_number": {"type": "integer", "minimum": 1},
                    "provider_id": {"type": "string"},
                    "service_code": {"type": "string"},
                    "service_date": {
                        "type": "string",
                        "description": "ISO 8601 date YYYY-MM-DD",
                    },
                    "billed_amount_minor_units": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Integer minor units (e.g. paise); do not guess",
                    },
                    "diagnosis_code": {"type": "string"},
                },
                "required": [
                    "line_number",
                    "provider_id",
                    "service_code",
                    "service_date",
                    "billed_amount_minor_units",
                    "diagnosis_code",
                ],
            },
        },
    },
    "required": ["member_id", "lines"],
}


class ClaimExtractionError(Exception):
    """Extraction could not produce a canonical Claim. No facts were invented."""


class ClaimExtractionValidationError(ClaimExtractionError):
    """Malformed output, missing required fields, or invalid types."""


class ClaimExtractionApiError(ClaimExtractionError):
    """Gemini / HTTP client failure. Message must never include the API key."""


class ExtractedClaimLineFacts(BaseModel):
    """Line facts Gemini may fill — a subset of ClaimLine, no computed amounts."""

    model_config = ConfigDict(extra="ignore")

    line_number: StrictInt = Field(ge=1)
    provider_id: str = Field(min_length=1)
    service_code: str = Field(min_length=1)
    service_date: date
    billed_amount_minor_units: StrictInt = Field(ge=0)
    diagnosis_code: str = Field(min_length=1)

    @field_validator("provider_id", "service_code", "diagnosis_code")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class ExtractedClaimFacts(BaseModel):
    """Claim facts Gemini may fill — no outcome, payment, or reason codes."""

    model_config = ConfigDict(extra="ignore")

    member_id: str = Field(min_length=1)
    lines: list[ExtractedClaimLineFacts] = Field(min_length=1)

    @field_validator("member_id")
    @classmethod
    def _strip_member_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class ClaimExtractor(Protocol):
    """Application port. Implementations live in infrastructure; domain does not see this."""

    def extract(
        self,
        unstructured_text: str,
        *,
        claim_id: str,
        submitted_at: datetime,
    ) -> Claim:
        """Return a canonical Claim. Must not adjudicate."""


def parse_extracted_facts(payload: object) -> ExtractedClaimFacts:
    """Validate a parsed JSON object. Does not invent missing fields."""
    if not isinstance(payload, dict):
        raise ClaimExtractionValidationError("extracted payload must be a JSON object")
    _reject_adjudication_fields(payload)
    try:
        return ExtractedClaimFacts.model_validate(payload)
    except ValidationError as exc:
        raise ClaimExtractionValidationError("extracted facts failed schema validation") from exc


def to_canonical_claim(
    facts: ExtractedClaimFacts,
    *,
    claim_id: str,
    submitted_at: datetime,
) -> Claim:
    """Map validated facts to the existing Claim / ClaimLine model.

    claim_id and submitted_at are assigned by the caller, not by Gemini.
    Line ids are derived as ``{claim_id}-L{line_number}``.
    """
    if not claim_id or not claim_id.strip():
        raise ClaimExtractionValidationError("claim_id must be non-empty")
    lines = tuple(
        ClaimLine(
            id=f"{claim_id}-L{line.line_number}",
            claim_id=claim_id,
            line_number=line.line_number,
            provider_id=line.provider_id,
            service_code=line.service_code,
            service_date=line.service_date,
            billed_amount=Money(line.billed_amount_minor_units),
            diagnosis_code=line.diagnosis_code,
        )
        for line in facts.lines
    )
    try:
        return Claim(
            id=claim_id,
            member_id=facts.member_id,
            submitted_at=submitted_at,
            lines=lines,
        )
    except ValueError as exc:
        raise ClaimExtractionValidationError("extracted facts are not a valid Claim") from exc


def _reject_adjudication_fields(payload: dict[str, Any]) -> None:
    present = _ADJUDICATION_FIELD_NAMES.intersection(payload)
    if present:
        raise ClaimExtractionValidationError(
            "extraction included adjudication fields, which Gemini must not produce"
        )
    lines = payload.get("lines")
    if not isinstance(lines, list):
        return
    for line in lines:
        if isinstance(line, dict) and _ADJUDICATION_FIELD_NAMES.intersection(line):
            raise ClaimExtractionValidationError(
                "extraction included adjudication fields, which Gemini must not produce"
            )
