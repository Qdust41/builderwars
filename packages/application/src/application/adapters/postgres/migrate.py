"""Forward-only SQL migrations for the PostgreSQL adapters.

Migrations are the ``migrations/NNNN_<name>.sql`` files next to this module, applied in
order, each in its own transaction, and recorded in ``schema_migrations``. A transaction-level
advisory lock serialises concurrent runners (two Lambdas cold-starting at once, say).

    uv run python -m application.adapters.postgres            # apply pending
    uv run python -m application.adapters.postgres --status   # list, change nothing

The connection string comes from ``--database-url`` or ``DATABASE_URL``.
"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any, Final

import psycopg
from psycopg import sql

# Arbitrary constant shared by every runner: pg_advisory_xact_lock key for migrations.
_LOCK_KEY: Final[int] = 0x6277_6D69_6772  # "bwmigr"
_FILENAME: Final = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class SchemaNotCurrentError(RuntimeError):
    """The database is missing migrations this code needs."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    name: str
    sql: str


def available_migrations() -> list[Migration]:
    folder = resources.files("application.adapters.postgres") / "migrations"
    found: list[Migration] = []
    for entry in folder.iterdir():
        match = _FILENAME.match(entry.name)
        if match is None:
            continue
        found.append(Migration(match.group(1), entry.name, entry.read_text(encoding="utf-8")))
    found.sort(key=lambda m: m.version)
    versions = [m.version for m in found]
    if len(set(versions)) != len(versions):
        raise RuntimeError(f"duplicate migration versions: {versions}")
    return found


def _ensure_table(conn: psycopg.Connection[Any]) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version text PRIMARY KEY,"
        " name text NOT NULL,"
        " applied_at timestamptz NOT NULL DEFAULT now())"
    )


def applied_versions(conn: psycopg.Connection[Any]) -> set[str]:
    exists = conn.execute("SELECT to_regclass('schema_migrations') IS NOT NULL").fetchone()
    if not exists or not exists[0]:
        return set()
    return {str(row[0]) for row in conn.execute("SELECT version FROM schema_migrations")}


def pending_migrations(conn: psycopg.Connection[Any]) -> list[Migration]:
    done = applied_versions(conn)
    return [m for m in available_migrations() if m.version not in done]


def migrate(conninfo: str) -> list[str]:
    """Apply every pending migration. Returns the file names applied, in order."""
    applied: list[str] = []
    with psycopg.connect(conninfo) as conn:
        for migration in available_migrations():
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
                _ensure_table(conn)
                already = conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = %s", (migration.version,)
                ).fetchone()
                if already:
                    continue
                conn.execute(sql.SQL(migration.sql))
                conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                    (migration.version, migration.name),
                )
                applied.append(migration.name)
    return applied


def check_schema_current(conn: psycopg.Connection[Any]) -> None:
    """Fail fast at startup instead of on the first query against a missing table."""
    missing = pending_migrations(conn)
    if missing:
        names = ", ".join(m.name for m in missing)
        raise SchemaNotCurrentError(
            f"database schema is missing migrations: {names}. "
            "Run: uv run python -m application.adapters.postgres"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply PostgreSQL schema migrations")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--status", action="store_true", help="list pending, change nothing")
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("set DATABASE_URL or pass --database-url")

    if args.status:
        with psycopg.connect(args.database_url) as conn:
            pending = pending_migrations(conn)
        for m in pending:
            print(f"pending  {m.name}")
        print(f"{len(pending)} pending")
        return 1 if pending else 0

    applied = migrate(args.database_url)
    for name in applied:
        print(f"applied  {name}")
    print(f"{len(applied)} applied; schema is current")
    return 0
