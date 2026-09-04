"""API tests for closing invariant (HTTP 409) behavior."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.application.submit_claim import AccumulatorLimitExceededError
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


def test_closing_invariant_failure_returns_409_and_leaves_no_claim(
    client: TestClient,
) -> None:
    with patch(
        "app.application.submit_claim._assert_within_limits",
        side_effect=AccumulatorLimitExceededError("benefit limit exceeded"),
    ):
        response = client.post(
            "/claims",
            json={
                "id": "invariant-fail",
                "member_id": "m1",
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
    assert response.status_code == 409
    assert response.json() == {"detail": "Accumulator limit would be exceeded"}

    missing = client.get("/claims/invariant-fail")
    assert missing.status_code == 404
