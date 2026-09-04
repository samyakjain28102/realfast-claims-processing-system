"""HTTP exception handlers — identifiers only, no PHI in error bodies."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.application.claim_queries import ClaimNotFoundError, MemberNotFoundError
from app.application.submit_claim import (
    AccumulatorLimitExceededError,
    PlanNotFoundError,
    PolicyNotFoundError,
    ProviderNotFoundError,
    SubmitClaimError,
)
from app.application.submit_claim import MemberNotFoundError as SubmitMemberNotFoundError


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ClaimNotFoundError)
    async def claim_not_found(
        _request: Request, exc: ClaimNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": "Claim not found"},
        )

    @app.exception_handler(MemberNotFoundError)
    @app.exception_handler(SubmitMemberNotFoundError)
    async def member_not_found(
        _request: Request, _exc: Exception
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": "Member not found"},
        )

    @app.exception_handler(ProviderNotFoundError)
    async def provider_not_found(
        _request: Request, _exc: ProviderNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": "Provider not found"},
        )

    @app.exception_handler(PolicyNotFoundError)
    async def policy_not_found(
        _request: Request, _exc: PolicyNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "No eligible policy for claim"},
        )

    @app.exception_handler(PlanNotFoundError)
    async def plan_not_found(
        _request: Request, _exc: PlanNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "Plan not found for policy"},
        )

    @app.exception_handler(AccumulatorLimitExceededError)
    async def limit_exceeded(
        _request: Request, _exc: AccumulatorLimitExceededError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "Accumulator limit would be exceeded"},
        )

    @app.exception_handler(SubmitClaimError)
    async def submit_claim_error(
        _request: Request, _exc: SubmitClaimError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": "Claim could not be submitted"},
        )
