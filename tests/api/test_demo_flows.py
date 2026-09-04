"""API smoke tests for the three demo narrative flows."""

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


def _line(
    *,
    line_number: int,
    service_code: str = "PHYSIO-30",
    billed: int = 5_000,
    service_date: str = "2026-03-15",
) -> dict:
    return {
        "line_number": line_number,
        "provider_id": "prov1",
        "service_code": service_code,
        "service_date": service_date,
        "billed_amount_minor": billed,
        "diagnosis_code": "M54.5",
    }


def _submit_body(*, claim_id: str, lines: list[dict]) -> dict:
    return {
        "id": claim_id,
        "member_id": "m1",
        "submitted_at": "2026-03-20T10:00:00",
        "lines": lines,
    }


def test_demo_flow_1_clean_claim_shows_deductible_split_and_explanation(
    client: TestClient,
) -> None:
    """Multiple covered lines with deductible consumption and above-allowed split."""
    response = client.post(
        "/claims",
        json=_submit_body(
            claim_id="clean-1",
            lines=[
                _line(line_number=1),
                _line(line_number=2, service_date="2026-03-16"),
            ],
        ),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["rejected"] is False
    assert body["adjudication_state"] == "APPROVED"
    assert len(body["lines"]) == 2

    first = body["lines"][0]["decision"]
    assert first is not None
    assert first["outcome"] == "APPROVED"
    assert first["amounts"]["plan_paid_minor"] == 0
    assert first["amounts"]["deductible_applied_minor"] == 4_000
    assert first["amounts"]["above_allowed_minor"] == 1_000
    reason_codes = {item["code"] for item in first["reasons"]}
    assert "MEM_DEDUCTIBLE" in reason_codes
    assert "MEM_ABOVE_ALLOWED" in reason_codes
    assert len(first["trace"]) >= 1

    detail = client.get("/claims/clean-1")
    assert detail.status_code == 200
    assert detail.json()["id"] == "clean-1"

    accumulators = client.get("/members/m1/accumulators")
    assert accumulators.status_code == 200
    deductible = next(
        row for row in accumulators.json()["balances"] if row["scope"] == "DEDUCTIBLE"
    )
    assert deductible["consumed"] == 8_000


def test_demo_flow_2_mixed_claim_partial_approval_and_review(
    client: TestClient,
) -> None:
    """Paid, excluded, limit-partial, and NEEDS_REVIEW lines on one claim."""
    deduct = client.post(
        "/claims",
        json=_submit_body(
            claim_id="setup-deduct",
            lines=[
                _line(line_number=1, service_date="2026-03-01"),
                _line(line_number=2, service_date="2026-03-02"),
                _line(line_number=3, service_date="2026-03-03"),
            ],
        ),
    )
    assert deduct.status_code == 201

    limit = client.post(
        "/claims",
        json=_submit_body(
            claim_id="setup-limit",
            lines=[_line(line_number=1, service_date="2026-03-04", billed=3_000)],
        ),
    )
    assert limit.status_code == 201

    response = client.post(
        "/claims",
        json=_submit_body(
            claim_id="mixed-1",
            lines=[
                _line(line_number=1, service_date="2026-03-10"),
                _line(
                    line_number=2,
                    service_code="COSMETIC-1",
                    billed=10_000,
                    service_date="2026-03-11",
                ),
                _line(line_number=3, service_date="2026-03-12"),
                _line(
                    line_number=4,
                    service_code="NOT-IN-CATALOG",
                    billed=1_000,
                    service_date="2026-03-13",
                ),
            ],
        ),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["adjudication_state"] == "UNDER_REVIEW"
    assert body["settlement_state"] == "DUE"
    assert body["payable_minor"] == 5_000

    by_number = {line["line_number"]: line for line in body["lines"]}
    assert by_number[1]["decision"]["outcome"] == "APPROVED"
    assert by_number[2]["decision"]["outcome"] == "DENIED"
    assert "DEN_EXCLUDED" in {
        r["code"] for r in by_number[2]["decision"]["reasons"]
    }
    assert by_number[3]["decision"]["outcome"] == "PARTIALLY_APPROVED"
    assert by_number[3]["decision"]["amounts"]["plan_paid_minor"] == 1_000
    assert by_number[4]["decision"]["outcome"] == "NEEDS_REVIEW"

    listed = client.get("/claims", params={"member_id": "m1"})
    assert listed.status_code == 200
    claim_ids = {item["id"] for item in listed.json()["claims"]}
    assert "mixed-1" in claim_ids


def test_demo_flow_3_denied_line_is_visible_for_future_dispute(
    client: TestClient,
) -> None:
    """Appealable denial is returned intact; dispute endpoints are not in scope yet."""
    response = client.post(
        "/claims",
        json=_submit_body(
            claim_id="dispute-setup",
            lines=[_line(line_number=1, service_code="COSMETIC-1", billed=10_000)],
        ),
    )
    assert response.status_code == 201
    body = response.json()
    decision = body["lines"][0]["decision"]
    assert decision["outcome"] == "DENIED"
    excluded = next(r for r in decision["reasons"] if r["code"] == "DEN_EXCLUDED")
    assert excluded["appealable"] is True

    fetched = client.get("/claims/dispute-setup")
    assert fetched.status_code == 200
    assert fetched.json()["lines"][0]["decision"]["id"] == decision["id"]


def test_error_responses_do_not_echo_phi(client: TestClient) -> None:
    response = client.post(
        "/claims",
        json={
            "id": "bad-member",
            "member_id": "missing-member",
            "submitted_at": "2026-03-20T10:00:00",
            "lines": [
                {
                    "line_number": 1,
                    "provider_id": "prov1",
                    "service_code": "PHYSIO-30",
                    "service_date": "2026-03-15",
                    "billed_amount_minor": 5000,
                    "diagnosis_code": "M54.5",
                }
            ],
        },
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Member not found"}
    assert "M54.5" not in response.text
