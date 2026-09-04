"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.infrastructure.db import SqliteDatabase


def get_db(request: Request) -> SqliteDatabase:
    return request.app.state.db
