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


def test_demo_flow_3_dispute_resolve_pay_and_eob(client: TestClient) -> None:
    """Denied line → dispute → fact correction → payment → EOB and accumulators."""
    # Burn most of the seeded ₹100 deductible so the appealed physio line pays out.
    setup = client.post(
        "/claims",
        json=_submit_body(
            claim_id="dispute-setup-prior",
            lines=[
                _line(line_number=1, service_date="2026-03-01"),
                _line(line_number=2, service_date="2026-03-02"),
            ],
        ),
    )
    assert setup.status_code == 201

    submit = client.post(
        "/claims",
        json=_submit_body(
            claim_id="dispute-setup",
            lines=[_line(line_number=1, service_code="COSMETIC-1", billed=10_000)],
        ),
    )
    assert submit.status_code == 201
    body = submit.json()
    decision = body["lines"][0]["decision"]
    assert decision["outcome"] == "DENIED"
    assert body["payable_minor"] == 0
    original_decision_id = decision["id"]

    dispute = client.post(
        "/claims/dispute-setup/lines/1/disputes",
        json={"member_reason": "Should be covered as physio"},
    )
    assert dispute.status_code == 201
    under_review = dispute.json()
    assert under_review["adjudication_state"] == "UNDER_REVIEW"
    assert under_review["lines"][0]["line_state"] == "UNDER_APPEAL"
    assert under_review["lines"][0]["decision"]["id"] == original_decision_id

    resolve = client.post(
        "/reviews/dispute-setup-L1/resolve",
        json={
            "mode": "CORRECT_FACTS",
            "reviewer_id": "rev1",
            "note": "Mapped to physio catalogue entry",
            "corrections": {"service_code": "PHYSIO-30"},
        },
    )
    assert resolve.status_code == 200
    approved = resolve.json()
    assert approved["adjudication_state"] == "APPROVED"
    assert approved["settlement_state"] == "DUE"
    assert approved["payable_minor"] == 2_000
    new_decision = approved["lines"][0]["decision"]
    assert new_decision["outcome"] == "APPROVED"
    assert new_decision["id"] != original_decision_id
    assert new_decision["sequence"] == 2
    assert new_decision["amounts"]["plan_paid_minor"] == 2_000

    payment = client.post(
        "/claims/dispute-setup/payments",
        json={"amount_minor": 2_000, "reference": "NEFT-1"},
    )
    assert payment.status_code == 201
    settled = payment.json()
    assert settled["settlement_state"] == "SETTLED"
    assert settled["payable_minor"] == 2_000

    eob = client.get("/claims/dispute-setup/eob")
    assert eob.status_code == 200
    eob_body = eob.json()
    assert eob_body["payable_minor"] == 2_000
    assert eob_body["paid_minor"] == 2_000
    assert eob_body["lines"][0]["outcome"] == "APPROVED"
    assert eob_body["payments"][0]["reference"] == "NEFT-1"

    accumulators = client.get("/members/m1/accumulators")
    assert accumulators.status_code == 200
    physio = next(
        row
        for row in accumulators.json()["balances"]
        if row["scope"] == "BENEFIT_AMOUNT" and row["benefit_code"] == "PHYSIO"
    )
    assert physio["consumed"] == 2_000


def test_validation_errors_do_not_echo_diagnosis_code(client: TestClient) -> None:
    """Malformed bodies must not echo sensitive fields such as diagnosis_code in 422 responses."""
    response = client.post(
        "/claims",
        json={
            "id": "bad-shape",
            "member_id": "m1",
            "submitted_at": "2026-03-20T10:00:00",
            "lines": [
                {
                    "line_number": 1,
                    "provider_id": "prov1",
                    "service_code": "PHYSIO-30",
                    "service_date": "2026-03-15",
                    "billed_amount_minor": "not-an-int",
                    "diagnosis_code": "SECRET-DX-99",
                }
            ],
        },
    )
    assert response.status_code == 422
    assert "SECRET-DX-99" not in response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    for item in detail:
        assert "input" not in item
        assert "SECRET-DX-99" not in str(item)


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
