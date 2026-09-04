"""API tests for POST /claims/{id}/lines/{n}/disputes."""

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


def _submit(client: TestClient, claim_id: str, service_code: str, billed: int) -> dict:
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
                    "service_code": service_code,
                    "service_date": "2026-03-15",
                    "billed_amount_minor": billed,
                    "diagnosis_code": "M54.5",
                }
            ],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_denied_line_can_be_disputed_via_http(client: TestClient) -> None:
    submitted = _submit(client, "disp-1", "COSMETIC-1", 10_000)
    decision_id = submitted["lines"][0]["decision"]["id"]
    response = client.post(
        "/claims/disp-1/lines/1/disputes",
        json={"member_reason": "this should have been covered"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["adjudication_state"] == "UNDER_REVIEW"
    assert body["lines"][0]["line_state"] == "UNDER_APPEAL"
    assert body["lines"][0]["decision"]["id"] == decision_id
    assert body["lines"][0]["decision"]["outcome"] == "DENIED"


def test_deductible_approval_cannot_be_disputed_via_http(client: TestClient) -> None:
    submitted = _submit(client, "disp-2", "PHYSIO-30", 4_000)
    assert submitted["lines"][0]["decision"]["outcome"] == "APPROVED"
    response = client.post(
        "/claims/disp-2/lines/1/disputes",
        json={"member_reason": "I dispute the deductible"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Line is not appealable"}
    fetched = client.get("/claims/disp-2")
    assert fetched.json()["lines"][0]["line_state"] == "APPROVED"
    assert fetched.json()["adjudication_state"] == "APPROVED"


def test_dispute_request_rejects_computed_value_overrides(client: TestClient) -> None:
    _submit(client, "disp-3", "COSMETIC-1", 10_000)
    response = client.post(
        "/claims/disp-3/lines/1/disputes",
        json={
            "member_reason": "please pay this",
            "plan_paid_minor": 10_000,
            "outcome": "APPROVED",
        },
    )
    assert response.status_code == 422
