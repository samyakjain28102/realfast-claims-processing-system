"""API tests for POST /reviews/{line_id}/resolve."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.infrastructure.db import open_database
from app.seed.fixtures import load_reference_data


@pytest.fixture
def client() -> TestClient:
    db = open_database(check_same_thread=False)
    load_reference_data(db)
    app = create_app(db=db)
    with TestClient(app) as test_client:
        yield test_client
    db.close()


def _submit_unknown(client: TestClient, claim_id: str = "review-1") -> str:
    response = client.post(
        "/claims",
        json={
            "id": claim_id,
            "member_id": "m1",
            "submitted_at": "2026-03-20T10:00:00",
            "lines": [
                {
                    "line_number": 1,
                    "provider_id": "prov1",
                    "service_code": "NOT-IN-CATALOG",
                    "service_date": "2026-03-15",
                    "billed_amount_minor": 5000,
                    "diagnosis_code": "M54.5",
                }
            ],
        },
    )
    assert response.status_code == 201
    line = response.json()["lines"][0]
    assert line["decision"]["outcome"] == "NEEDS_REVIEW"
    return line["id"]


def test_reviewer_cannot_modify_computed_values(client: TestClient) -> None:
    line_id = _submit_unknown(client)
    response = client.post(
        f"/reviews/{line_id}/resolve",
        json={
            "mode": "CORRECT_FACTS",
            "reviewer_id": "rev1",
            "note": "try to set payment",
            "plan_paid_minor": 4000,
            "allowed_amount_minor": 4000,
            "deductible_applied_minor": 0,
            "denied_amount_minor": 0,
            "outcome": "APPROVED",
            "reason_codes": ["INFO_COVERED"],
            "corrections": {"service_code": "PHYSIO-30"},
        },
    )
    assert response.status_code == 422
    current = client.get("/claims/review-1")
    assert current.json()["lines"][0]["decision"]["outcome"] == "NEEDS_REVIEW"
    assert current.json()["lines"][0]["decision"]["sequence"] == 1


def test_reviewer_cannot_put_computed_values_inside_corrections(
    client: TestClient,
) -> None:
    line_id = _submit_unknown(client, claim_id="review-2")
    response = client.post(
        f"/reviews/{line_id}/resolve",
        json={
            "mode": "CORRECT_FACTS",
            "reviewer_id": "rev1",
            "note": "try to set payment in corrections",
            "corrections": {
                "service_code": "PHYSIO-30",
                "plan_paid_minor": 4000,
                "outcome": "APPROVED",
            },
        },
    )
    assert response.status_code == 422


def test_correct_unknown_service_via_http(client: TestClient) -> None:
    line_id = _submit_unknown(client, claim_id="review-3")
    response = client.post(
        f"/reviews/{line_id}/resolve",
        json={
            "mode": "CORRECT_FACTS",
            "reviewer_id": "rev1",
            "note": "mapped to physio",
            "corrections": {"service_code": "PHYSIO-30"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["adjudication_state"] == "APPROVED"
    decision = body["lines"][0]["decision"]
    assert decision["sequence"] == 2
    assert decision["outcome"] == "APPROVED"
    assert decision["source"] == "RULES"
    assert decision["plan_version"] == 1
