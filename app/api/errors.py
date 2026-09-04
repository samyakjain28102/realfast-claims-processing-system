"""HTTP exception handlers — identifiers only, no PHI in error bodies."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.application.claim_queries import ClaimNotFoundError, MemberNotFoundError
from app.application.record_payment import (
    PaymentAmountMismatchError,
    PaymentNotAllowedError,
    PaymentWhileUnderReviewError,
    RecordPaymentError,
)
from app.application.file_dispute import (
    DisputeAlreadyOpenError,
    DisputeLineNotFoundError,
    DisputeNotAppealableError,
    FileDisputeError,
    LineNotDisputableError,
)
from app.application.resolve_review import (
    InvalidCorrectionError,
    InvalidResolveRequestError,
    LineNotFoundError,
    LineNotInReviewError,
    ResolveReviewError,
    UpholdNotAllowedError,
)
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

    @app.exception_handler(LineNotFoundError)
    async def review_line_not_found(
        _request: Request, _exc: LineNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": "Line not found"},
        )

    @app.exception_handler(LineNotInReviewError)
    async def review_line_not_in_review(
        _request: Request, _exc: LineNotInReviewError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "Line is not awaiting review"},
        )

    @app.exception_handler(UpholdNotAllowedError)
    async def review_uphold_not_allowed(
        _request: Request, _exc: UpholdNotAllowedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": "Uphold requires an open dispute"},
        )

    @app.exception_handler(InvalidCorrectionError)
    async def review_invalid_correction(
        _request: Request, _exc: InvalidCorrectionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "Correction would invalidate the claim"},
        )

    @app.exception_handler(InvalidResolveRequestError)
    async def review_invalid_request(
        _request: Request, _exc: InvalidResolveRequestError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid review resolution request"},
        )

    @app.exception_handler(ResolveReviewError)
    async def review_resolve_error(
        _request: Request, _exc: ResolveReviewError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": "Review could not be resolved"},
        )

    @app.exception_handler(DisputeLineNotFoundError)
    async def dispute_line_not_found(
        _request: Request, _exc: DisputeLineNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": "Line not found"},
        )

    @app.exception_handler(DisputeNotAppealableError)
    async def dispute_not_appealable(
        _request: Request, _exc: DisputeNotAppealableError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": "Line is not appealable"},
        )

    @app.exception_handler(DisputeAlreadyOpenError)
    async def dispute_already_open(
        _request: Request, _exc: DisputeAlreadyOpenError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "A dispute is already open"},
        )

    @app.exception_handler(LineNotDisputableError)
    async def line_not_disputable(
        _request: Request, _exc: LineNotDisputableError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "Line cannot be disputed"},
        )

    @app.exception_handler(FileDisputeError)
    async def file_dispute_error(
        _request: Request, _exc: FileDisputeError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": "Dispute could not be filed"},
        )

    @app.exception_handler(PaymentWhileUnderReviewError)
    async def payment_under_review(
        _request: Request, _exc: PaymentWhileUnderReviewError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "Payment is not allowed while the claim is under review"},
        )

    @app.exception_handler(PaymentAmountMismatchError)
    async def payment_amount_mismatch(
        _request: Request, _exc: PaymentAmountMismatchError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": "Payment must equal the amount due"},
        )

    @app.exception_handler(PaymentNotAllowedError)
    async def payment_not_allowed(
        _request: Request, _exc: PaymentNotAllowedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "Payment is not allowed"},
        )

    @app.exception_handler(RecordPaymentError)
    async def record_payment_error(
        _request: Request, _exc: RecordPaymentError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": "Payment could not be recorded"},
        )
