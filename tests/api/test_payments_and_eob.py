"""API tests for POST /claims/{id}/payments and GET /claims/{id}/eob."""

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


def _submit(client: TestClient, claim_id: str, lines: list[dict]) -> dict:
    response = client.post(
        "/claims",
        json={
            "id": claim_id,
            "member_id": "m1",
            "submitted_at": "2026-03-20T10:00:00",
            "lines": lines,
        },
    )
    assert response.status_code == 201
    return response.json()


def _physio_line(number: int, service_date: str = "2026-03-15") -> dict:
    return {
        "line_number": number,
        "provider_id": "prov1",
        "service_code": "PHYSIO-30",
        "service_date": service_date,
        "billed_amount_minor": 5_000,
        "diagnosis_code": "M54.5",
    }


def test_http_payment_after_approval_and_eob_matches_decision(
    client: TestClient,
) -> None:
    # Exhaust deductible so the next claim has a payable amount.
    setup = _submit(
        client,
        "setup-pay",
        [_physio_line(1, "2026-03-01"), _physio_line(2, "2026-03-02")],
    )
    assert setup["payable_minor"] == 0

    submitted = _submit(client, "pay-1", [_physio_line(1, "2026-03-15")])
    assert submitted["adjudication_state"] == "APPROVED"
    assert submitted["settlement_state"] == "DUE"
    payable = submitted["payable_minor"]
    assert payable > 0
    decision_id = submitted["lines"][0]["decision"]["id"]

    too_small = client.post(
        "/claims/pay-1/payments",
        json={"amount_minor": payable - 1, "reference": "chk-partial"},
    )
    assert too_small.status_code == 400

    paid = client.post(
        "/claims/pay-1/payments",
        json={"amount_minor": payable, "reference": "chk-1"},
    )
    assert paid.status_code == 201
    assert paid.json()["settlement_state"] == "SETTLED"
    assert paid.json()["lines"][0]["decision"]["id"] == decision_id

    eob = client.get("/claims/pay-1/eob")
    assert eob.status_code == 200
    body = eob.json()
    assert body["payable_minor"] == payable
    assert body["paid_minor"] == payable
    assert body["lines"][0]["outcome"] == "APPROVED"
    assert body["lines"][0]["explanations"]
    assert body["lines"][0]["amounts"]["plan_paid_minor"] == payable
    assert body["payments"][0]["reference"] == "chk-1"


def test_http_payment_rejected_while_under_review(client: TestClient) -> None:
    submitted = _submit(
        client,
        "pay-review",
        [
            _physio_line(1),
            {
                "line_number": 2,
                "provider_id": "prov1",
                "service_code": "NOT-IN-CATALOG",
                "service_date": "2026-03-16",
                "billed_amount_minor": 1_000,
                "diagnosis_code": "M54.5",
            },
        ],
    )
    assert submitted["adjudication_state"] == "UNDER_REVIEW"
    response = client.post(
        "/claims/pay-review/payments",
        json={"amount_minor": submitted["payable_minor"] or 1, "reference": "chk-1"},
    )
    assert response.status_code == 409
    assert response.json() == {
        "detail": "Payment is not allowed while the claim is under review"
    }
