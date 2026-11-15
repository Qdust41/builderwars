from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from application.adapters import memory
from application.services import (
    Authorizer,
    CommandService,
    DeviceEventPublisher,
    DeviceMessageIngestService,
    DeviceService,
    JobService,
    ProjectService,
    SessionService,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "contracts" / "device" / "fixtures"

# Repository-backed fixtures run once per backend. The PostgreSQL run needs a disposable database
# (every table is truncated between tests); without TEST_DATABASE_URL it is skipped. Locally:
#   docker compose --profile postgres up -d db
#   TEST_DATABASE_URL=postgresql://builderwars:builderwars-local@localhost:5432/builderwars_test
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BACKENDS = ["memory", pytest.param("postgres", marks=pytest.mark.postgres)]


@pytest.fixture(scope="session")
def pg_pool() -> Iterator[Any]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set; PostgreSQL backend tests skipped")
    from application.adapters import postgres

    postgres.migrate(TEST_DATABASE_URL)
    pool = postgres.create_pool(TEST_DATABASE_URL, max_size=4, name="builderwars-tests")
    yield pool
    pool.close()


@pytest.fixture
def pg(pg_pool: Any) -> Any:
    """Fresh PostgreSQL repositories over an emptied schema."""
    from application.adapters import postgres

    with pg_pool.connection() as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
                " AND tablename <> 'schema_migrations'"
            )
        ]
        conn.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
    return postgres.PostgresRepositories.from_pool(pg_pool)


@pytest.fixture(params=BACKENDS)
def backend(request: pytest.FixtureRequest) -> str:
    return str(request.param)


class PgRawView:
    """Reads the PostgreSQL raw/quarantine tables back in the in-memory adapter's shapes."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def put(self, **kw: Any) -> None:
        self._store.put(**kw)

    def quarantine(self, **kw: Any) -> None:
        self._store.quarantine(**kw)

    @property
    def items(self) -> list[tuple[str, str, Any, bytes]]:
        rows = self._store._all(
            "SELECT device_id, message_id, received_at, body FROM raw_device_messages ORDER BY id"
        )
        return [(r["device_id"], r["message_id"], r["received_at"], r["body"]) for r in rows]

    @property
    def quarantined(self) -> list[tuple[str | None, Any, bytes, str]]:
        rows = self._store._all(
            "SELECT device_id, received_at, body, reason FROM quarantined_device_messages"
            " ORDER BY id"
        )
        return [(r["device_id"], r["received_at"], r["body"], r["reason"]) for r in rows]


class PgTelemetryView:
    """Reads the PostgreSQL telemetry tables back in the in-memory adapter's shapes."""

    def __init__(self, repo: Any) -> None:
        self._repo = repo

    def add_telemetry(self, **kw: Any) -> None:
        self._repo.add_telemetry(**kw)

    def add_log(self, **kw: Any) -> None:
        self._repo.add_log(**kw)

    def add_event(self, **kw: Any) -> None:
        self._repo.add_event(**kw)

    def recent_telemetry(self, device_id: str, *, limit: int) -> Any:
        return self._repo.recent_telemetry(device_id, limit=limit)

    def recent_logs(self, device_id: str, *, limit: int) -> Any:
        return self._repo.recent_logs(device_id, limit=limit)

    def _rows(self, table: str, columns: str) -> list[dict[str, object]]:
        return [dict(r) for r in self._repo._all(f"SELECT {columns} FROM {table} ORDER BY id")]

    @property
    def telemetry(self) -> list[dict[str, object]]:
        return self._rows("device_telemetry", "device_id, message_id, at, metrics")

    @property
    def logs(self) -> list[dict[str, object]]:
        return self._rows("device_logs", "device_id, message_id, at, level, message")

    @property
    def events(self) -> list[dict[str, object]]:
        return self._rows("device_events", "device_id, message_id, at, name, severity, detail")


@dataclass
class World:
    projects_repo: Any
    memberships: Any
    users: memory.InMemoryUserDirectory
    devices_repo: Any
    sessions_repo: Any
    jobs_repo: Any
    queue: memory.InMemoryJobQueue
    realtime: memory.RecordingRealtimePublisher
    authorizer: Authorizer
    projects: ProjectService
    devices: DeviceService
    sessions: SessionService
    jobs: JobService
    commands_repo: Any
    command_queue: memory.InMemoryCommandQueue
    commands: CommandService


@pytest.fixture
def world(backend: str, request: pytest.FixtureRequest) -> World:
    """Services over one repository backend; queues and realtime stay in-memory recorders."""
    if backend == "postgres":
        pg = request.getfixturevalue("pg")
        projects_repo, memberships, devices_repo = pg.projects, pg.memberships, pg.devices
        sessions_repo, jobs_repo, commands_repo = pg.sessions, pg.jobs, pg.commands
    else:
        projects_repo = memory.InMemoryProjectRepository()
        memberships = memory.InMemoryMembershipRepository()
        devices_repo = memory.InMemoryDeviceRepository()
        sessions_repo = memory.InMemorySessionRepository()
        jobs_repo = memory.InMemoryJobRepository()
        commands_repo = memory.InMemoryDeviceCommandRepository()
    users = memory.InMemoryUserDirectory()
    queue = memory.InMemoryJobQueue()
    realtime = memory.RecordingRealtimePublisher()
    authorizer = Authorizer(memberships)
    command_queue = memory.InMemoryCommandQueue()
    return World(
        projects_repo=projects_repo,
        memberships=memberships,
        users=users,
        devices_repo=devices_repo,
        sessions_repo=sessions_repo,
        jobs_repo=jobs_repo,
        queue=queue,
        realtime=realtime,
        authorizer=authorizer,
        projects=ProjectService(projects_repo, memberships, authorizer, users),
        devices=DeviceService(devices_repo, authorizer),
        sessions=SessionService(sessions_repo, devices_repo, authorizer, realtime),
        jobs=JobService(jobs_repo, devices_repo, queue, authorizer),
        commands_repo=commands_repo,
        command_queue=command_queue,
        commands=CommandService(commands_repo, devices_repo, command_queue, authorizer),
    )


@dataclass
class IngestWorld:
    service: DeviceMessageIngestService
    projects: Any
    devices: Any
    raw: Any  # .items / .quarantined, as memory.InMemoryRawMessageStore
    telemetry: Any  # .telemetry / .logs / .events, as memory.InMemoryTelemetryRepository
    commands: Any
    realtime: memory.RecordingRealtimePublisher


@pytest.fixture
def ingest(backend: str, request: pytest.FixtureRequest) -> IngestWorld:
    processed: Any
    sequences: Any
    if backend == "postgres":
        pg = request.getfixturevalue("pg")
        projects, devices, commands = pg.projects, pg.devices, pg.commands
        raw: Any = PgRawView(pg.raw_messages)
        telemetry: Any = PgTelemetryView(pg.telemetry)
        processed, sequences = pg.processed, pg.sequences
    else:
        projects = memory.InMemoryProjectRepository()
        devices = memory.InMemoryDeviceRepository()
        commands = memory.InMemoryDeviceCommandRepository()
        raw = memory.InMemoryRawMessageStore()
        telemetry = memory.InMemoryTelemetryRepository()
        processed = memory.InMemoryProcessedMessageStore()
        sequences = memory.InMemorySequenceTracker()
    realtime = memory.RecordingRealtimePublisher()
    service = DeviceMessageIngestService(
        devices=devices,
        processed=processed,
        raw_store=raw,
        telemetry=telemetry,
        sequences=sequences,
        commands=commands,
        events=DeviceEventPublisher(realtime),
    )
    return IngestWorld(service, projects, devices, raw, telemetry, commands, realtime)
