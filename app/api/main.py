"""FastAPI application entry point."""

from __future__ import annotations

import os

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.routers.claims import router as claims_router
from app.api.routers.members import router as members_router
from app.infrastructure.db import SqliteDatabase, open_database


def create_app(*, db: SqliteDatabase | None = None) -> FastAPI:
    """Build the API. Pass db in tests; otherwise open from CLAIMS_DATABASE."""
    app = FastAPI(title="Claims Processing System")
    app.state.db = db if db is not None else open_database(
        os.environ.get("CLAIMS_DATABASE", ":memory:"),
        check_same_thread=False,
    )
    register_exception_handlers(app)
    app.include_router(claims_router)
    app.include_router(members_router)
    return app


app = create_app()
