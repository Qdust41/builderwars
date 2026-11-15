"""PostgreSQL migrations and process wiring (API container, worker CLI)."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from application.adapters import postgres
from application.adapters.postgres.migrate import available_migrations
from application.services import IngestOutcome
from board_runtime.simulator import simulate
from workers.consumers import LocalHarness, read_jsonl
from workers.main import build_postgres_device_handler
from workers.settings import RepositoryBackend, WorkerSettings

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture
def database_url(pg: Any) -> str:
    """The test database, emptied (``pg`` truncates it)."""
    return os.environ["TEST_DATABASE_URL"]


@pytest.fixture
def empty_schema(pg_pool: Any) -> Iterator[str]:
    """A conninfo whose search_path is a brand-new, empty schema."""
    url = os.environ["TEST_DATABASE_URL"]
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS bw_migration_test CASCADE")
        conn.execute("CREATE SCHEMA bw_migration_test")
    yield make_conninfo(url, options="-c search_path=bw_migration_test")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA bw_migration_test CASCADE")


def test_migrations_apply_once_and_record_versions(empty_schema: str) -> None:
    with (
        psycopg.connect(empty_schema) as conn,
        pytest.raises(postgres.SchemaNotCurrentError, match=r"0001_initial\.sql"),
    ):
        postgres.check_schema_current(conn)

    names = [m.name for m in available_migrations()]
    assert postgres.migrate(empty_schema) == names
    assert postgres.migrate(empty_schema) == []  # idempotent

    with psycopg.connect(empty_schema) as conn:
        postgres.check_schema_current(conn)
        recorded = [r[0] for r in conn.execute("SELECT name FROM schema_migrations ORDER BY 1")]
    assert recorded == names


def test_api_refuses_to_start_on_an_unmigrated_database(empty_schema: str) -> None:
    from api.dependencies import build_container
    from api.settings import AppEnv, RepositoryBackend, Settings

    settings = Settings(
        app_env=AppEnv.TEST,
        repository_backend=RepositoryBackend.POSTGRES,
        database_url=empty_schema,
    )
    with pytest.raises(postgres.SchemaNotCurrentError):
        build_container(settings)


def test_worker_ingests_into_postgres_and_dedupes_replays(database_url: str) -> None:
    out = io.StringIO()
    simulate(device_id="sim-pg", count=4, seed=7, out=out)
    lines = out.getvalue()
    settings = WorkerSettings(
        app_env="test", repository_backend=RepositoryBackend.POSTGRES, database_url=database_url
    )
    handler, repos = build_postgres_device_handler(settings)
    try:
        harness = LocalHarness(handler)
        total = len(lines.strip().splitlines())
        assert harness.run(read_jsonl(io.StringIO(lines))) == {IngestOutcome.PROCESSED: total}
        assert harness.run(read_jsonl(io.StringIO(lines))) == {IngestOutcome.DUPLICATE: total}
        with repos.pool.connection() as conn:
            row = conn.execute("SELECT count(*) FROM device_telemetry").fetchone()
            raw = conn.execute("SELECT count(*) FROM raw_device_messages").fetchone()
        assert row == (4,)
        assert raw == (total,)
    finally:
        repos.close()


def test_worker_cli_runs_with_the_postgres_backend(database_url: str) -> None:
    sim = subprocess.run(
        [sys.executable, "-m", "board_runtime.simulator", "--count", "2", "--seed", "1"],
        check=True,
        capture_output=True,
        text=True,
    )
    env = {
        **os.environ,
        "APP_ENV": "test",
        "REPOSITORY_BACKEND": "postgres",
        "DATABASE_URL": database_url,
    }
    worker = subprocess.run(
        [sys.executable, "-m", "workers.main"],
        input=sim.stdout,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "summary: processed=5; stored in PostgreSQL" in worker.stdout
