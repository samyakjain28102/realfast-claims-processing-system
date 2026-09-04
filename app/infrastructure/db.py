"""SQLite connection setup. No domain rules live here."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import sqlite3

if TYPE_CHECKING:
    from app.infrastructure.repositories import (
        AccumulatorRepository,
        ClaimRepository,
        DisputeRepository,
        LineDecisionRepository,
        MemberRepository,
        PaymentRepository,
        PlanRepository,
        PolicyRepository,
        ProviderRepository,
        ReviewResolutionRepository,
        ServiceCatalogueRepository,
    )

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
BUSY_TIMEOUT_MS = 5000


def connect(
    database: str = ":memory:",
    *,
    uri: bool = False,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    """Open a sqlite3 connection in autocommit mode so callers own transactions."""
    connection = sqlite3.connect(
        database,
        uri=uri,
        isolation_level=None,
        check_same_thread=check_same_thread,
    )
    connection.row_factory = sqlite3.Row
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    """Apply WAL, busy timeout, foreign keys, and schema.sql."""
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA journal_mode = WAL")
    already_initialized = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'members'"
    ).fetchone()
    if already_initialized is None:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        connection.executescript(schema)
    connection.execute("PRAGMA foreign_keys = ON")


def open_database(
    database: str = ":memory:",
    *,
    uri: bool = False,
    check_same_thread: bool = True,
) -> SqliteDatabase:
    """Connect, initialize schema, and return a repository-bound wrapper."""
    connection = connect(
        database, uri=uri, check_same_thread=check_same_thread
    )
    initialize(connection)
    return SqliteDatabase(connection)


def open_shared_memory(*, name: str = "claims") -> SqliteDatabase:
    """In-memory database visible to multiple connections (threaded tests)."""
    return open_database(
        f"file:{name}?mode=memory&cache=shared",
        uri=True,
        check_same_thread=False,
    )


class SqliteDatabase:
    """Thin unit of work: connection, explicit transactions, repositories."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        from app.infrastructure.repositories import (
            AccumulatorRepository,
            ClaimRepository,
            DisputeRepository,
            LineDecisionRepository,
            MemberRepository,
            PaymentRepository,
            PlanRepository,
            PolicyRepository,
            ProviderRepository,
            ReviewResolutionRepository,
            ServiceCatalogueRepository,
        )

        self.connection = connection
        self.members: MemberRepository = MemberRepository(connection)
        self.providers: ProviderRepository = ProviderRepository(connection)
        self.plans: PlanRepository = PlanRepository(connection)
        self.policies: PolicyRepository = PolicyRepository(connection)
        self.catalogue: ServiceCatalogueRepository = ServiceCatalogueRepository(
            connection
        )
        self.claims: ClaimRepository = ClaimRepository(connection)
        self.decisions: LineDecisionRepository = LineDecisionRepository(
            connection
        )
        self.accumulators: AccumulatorRepository = AccumulatorRepository(
            connection
        )
        self.payments: PaymentRepository = PaymentRepository(connection)
        self.disputes: DisputeRepository = DisputeRepository(connection)
        self.reviews: ReviewResolutionRepository = ReviewResolutionRepository(
            connection
        )

    def begin_immediate(self) -> None:
        self.connection.execute("BEGIN IMMEDIATE")

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()
