"""PostgreSQL adapters for the repository ports (RDS in prod, a local Postgres in development).

Typical wiring::

    pool = create_pool(database_url)
    check_schema_current_with(pool)        # fail fast if migrations are missing
    repos = PostgresRepositories.from_pool(pool)

Schema changes are SQL files in ``migrations/``; apply them with
``uv run python -m application.adapters.postgres``.
"""

from __future__ import annotations

from dataclasses import dataclass

from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg_pool import ConnectionPool

from application.adapters.postgres.migrate import (
    SchemaNotCurrentError,
    check_schema_current,
    migrate,
)
from application.adapters.postgres.repositories import (
    PostgresDeviceCommandRepository,
    PostgresDeviceRepository,
    PostgresDeviceSetupRepository,
    PostgresJobRepository,
    PostgresMembershipRepository,
    PostgresProcessedMessageStore,
    PostgresProjectRepository,
    PostgresRawMessageStore,
    PostgresSensorRepository,
    PostgresSequenceTracker,
    PostgresSessionRepository,
    PostgresTargetBoardRepository,
    PostgresTelemetryRepository,
)


def create_pool(
    conninfo: str, *, min_size: int = 1, max_size: int = 5, name: str = "builderwars"
) -> ConnectionPool:
    """Open a connection pool. Sessions run in UTC so timestamps come back as UTC datetimes.

    Lambda: one pool per execution environment, ``max_size=1`` (one request at a time).
    """
    # Append rather than replace, so options already in the URL (search_path, say) survive.
    existing = str(conninfo_to_dict(conninfo).get("options") or "")
    options = f"{existing} -c TimeZone=UTC".strip()
    pool = ConnectionPool(
        make_conninfo(conninfo, options=options),
        min_size=min_size,
        max_size=max_size,
        name=name,
        open=False,
    )
    pool.open(wait=True, timeout=10)
    return pool


def check_schema_current_with(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        check_schema_current(conn)


@dataclass(frozen=True, slots=True)
class PostgresRepositories:
    """Every repository port, backed by one pool."""

    pool: ConnectionPool
    projects: PostgresProjectRepository
    memberships: PostgresMembershipRepository
    devices: PostgresDeviceRepository
    sessions: PostgresSessionRepository
    jobs: PostgresJobRepository
    commands: PostgresDeviceCommandRepository
    processed: PostgresProcessedMessageStore
    sequences: PostgresSequenceTracker
    raw_messages: PostgresRawMessageStore
    telemetry: PostgresTelemetryRepository
    setups: PostgresDeviceSetupRepository
    boards: PostgresTargetBoardRepository
    sensors: PostgresSensorRepository

    @classmethod
    def from_pool(cls, pool: ConnectionPool) -> PostgresRepositories:
        return cls(
            pool=pool,
            projects=PostgresProjectRepository(pool),
            memberships=PostgresMembershipRepository(pool),
            devices=PostgresDeviceRepository(pool),
            sessions=PostgresSessionRepository(pool),
            jobs=PostgresJobRepository(pool),
            commands=PostgresDeviceCommandRepository(pool),
            processed=PostgresProcessedMessageStore(pool),
            sequences=PostgresSequenceTracker(pool),
            raw_messages=PostgresRawMessageStore(pool),
            telemetry=PostgresTelemetryRepository(pool),
            setups=PostgresDeviceSetupRepository(pool),
            boards=PostgresTargetBoardRepository(pool),
            sensors=PostgresSensorRepository(pool),
        )

    def close(self) -> None:
        self.pool.close()


__all__ = [
    "PostgresDeviceCommandRepository",
    "PostgresDeviceRepository",
    "PostgresDeviceSetupRepository",
    "PostgresJobRepository",
    "PostgresMembershipRepository",
    "PostgresProcessedMessageStore",
    "PostgresProjectRepository",
    "PostgresRawMessageStore",
    "PostgresRepositories",
    "PostgresSensorRepository",
    "PostgresSequenceTracker",
    "PostgresSessionRepository",
    "PostgresTargetBoardRepository",
    "PostgresTelemetryRepository",
    "SchemaNotCurrentError",
    "check_schema_current",
    "check_schema_current_with",
    "create_pool",
    "migrate",
]
