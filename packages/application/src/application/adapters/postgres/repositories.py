"""PostgreSQL implementations of the repository ports (``application.ports.repositories``).

Each method runs in its own short transaction on a pooled connection. Multi-statement
atomicity across repositories (an outbox, say) is out of scope here; see workstream G.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from application.ports import DeviceLogEntry, TelemetrySample
from domain.devices import CommandStatus, ConnectionStatus, Device, DeviceCommand
from domain.jobs import Job, JobStatus, JobType
from domain.projects import Project, ProjectMembership, ProjectRole
from domain.sessions import Session, SessionStatus

Row = dict[str, Any]


class _Repo:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def _one(self, query: str, params: Sequence[object] = ()) -> Row | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            return cur.fetchone()

    def _all(self, query: str, params: Sequence[object] = ()) -> list[Row]:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def _exec(self, query: str, params: Sequence[object] = ()) -> int:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            return cur.rowcount


# --- projects -----------------------------------------------------------------------------------


def _project(row: Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        owner_user_id=row["owner_user_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class PostgresProjectRepository(_Repo):
    def add(self, project: Project) -> None:
        self._exec(
            "INSERT INTO projects (id, name, owner_user_id, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s)",
            (
                project.id,
                project.name,
                project.owner_user_id,
                project.created_at,
                project.updated_at,
            ),
        )

    def get(self, project_id: str) -> Project | None:
        row = self._one("SELECT * FROM projects WHERE id = %s", (project_id,))
        return _project(row) if row else None

    def list_by_ids(self, project_ids: Sequence[str]) -> list[Project]:
        if not project_ids:
            return []
        ids = list(project_ids)
        rows = self._all(
            "SELECT * FROM projects WHERE id = ANY(%s) ORDER BY array_position(%s, id)",
            (ids, ids),
        )
        return [_project(r) for r in rows]


def _membership(row: Row) -> ProjectMembership:
    return ProjectMembership(
        project_id=row["project_id"],
        user_id=row["user_id"],
        role=ProjectRole(row["role"]),
        created_at=row["created_at"],
    )


class PostgresMembershipRepository(_Repo):
    def add(self, membership: ProjectMembership) -> None:
        # Same key replaces, like the in-memory adapter (a role change re-adds the membership).
        self._exec(
            "INSERT INTO project_memberships (project_id, user_id, role, created_at)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (project_id, user_id) DO UPDATE"
            " SET role = EXCLUDED.role, created_at = EXCLUDED.created_at",
            (
                membership.project_id,
                membership.user_id,
                membership.role.value,
                membership.created_at,
            ),
        )

    def get(self, project_id: str, user_id: str) -> ProjectMembership | None:
        row = self._one(
            "SELECT * FROM project_memberships WHERE project_id = %s AND user_id = %s",
            (project_id, user_id),
        )
        return _membership(row) if row else None

    def list_for_user(self, user_id: str) -> list[ProjectMembership]:
        rows = self._all(
            "SELECT * FROM project_memberships WHERE user_id = %s ORDER BY created_at, project_id",
            (user_id,),
        )
        return [_membership(r) for r in rows]

    def list_for_project(self, project_id: str) -> list[ProjectMembership]:
        rows = self._all(
            "SELECT * FROM project_memberships WHERE project_id = %s ORDER BY created_at, user_id",
            (project_id,),
        )
        return [_membership(r) for r in rows]

    def remove(self, project_id: str, user_id: str) -> None:
        self._exec(
            "DELETE FROM project_memberships WHERE project_id = %s AND user_id = %s",
            (project_id, user_id),
        )


# --- devices ------------------------------------------------------------------------------------


def _device(row: Row) -> Device:
    return Device(
        id=row["id"],
        project_id=row["project_id"],
        display_name=row["display_name"],
        hardware_model=row["hardware_model"],
        extensions=frozenset(row["extensions"] or ()),
        firmware_version=row["firmware_version"],
        connection_status=ConnectionStatus(row["connection_status"]),
        last_seen_at=row["last_seen_at"],
        created_at=row["created_at"],
    )


_DEVICE_UPSERT = (
    "INSERT INTO devices (id, project_id, display_name, hardware_model, extensions,"
    " firmware_version, connection_status, last_seen_at, created_at)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


class PostgresDeviceRepository(_Repo):
    @staticmethod
    def _params(device: Device) -> tuple[object, ...]:
        return (
            device.id,
            device.project_id,
            device.display_name,
            device.hardware_model,
            sorted(device.extensions),
            device.firmware_version,
            device.connection_status.value,
            device.last_seen_at,
            device.created_at,
        )

    def add(self, device: Device) -> None:
        self._exec(_DEVICE_UPSERT, self._params(device))

    def save(self, device: Device) -> None:
        self._exec(
            _DEVICE_UPSERT + " ON CONFLICT (id) DO UPDATE SET"
            " project_id = EXCLUDED.project_id, display_name = EXCLUDED.display_name,"
            " hardware_model = EXCLUDED.hardware_model, extensions = EXCLUDED.extensions,"
            " firmware_version = EXCLUDED.firmware_version,"
            " connection_status = EXCLUDED.connection_status,"
            " last_seen_at = EXCLUDED.last_seen_at",
            self._params(device),
        )

    def get(self, device_id: str) -> Device | None:
        row = self._one("SELECT * FROM devices WHERE id = %s", (device_id,))
        return _device(row) if row else None

    def list_for_project(self, project_id: str) -> list[Device]:
        rows = self._all(
            "SELECT * FROM devices WHERE project_id = %s ORDER BY created_at, id", (project_id,)
        )
        return [_device(r) for r in rows]


# --- sessions -----------------------------------------------------------------------------------


def _session(row: Row) -> Session:
    return Session(
        id=row["id"],
        project_id=row["project_id"],
        created_by=row["created_by"],
        device_id=row["device_id"],
        status=SessionStatus(row["status"]),
        created_at=row["created_at"],
    )


class PostgresSessionRepository(_Repo):
    def add(self, session: Session) -> None:
        self._exec(
            "INSERT INTO sessions (id, project_id, created_by, device_id, status, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status",
            (
                session.id,
                session.project_id,
                session.created_by,
                session.device_id,
                session.status.value,
                session.created_at,
            ),
        )

    def get(self, session_id: str) -> Session | None:
        row = self._one("SELECT * FROM sessions WHERE id = %s", (session_id,))
        return _session(row) if row else None

    def list_for_project(self, project_id: str) -> list[Session]:
        rows = self._all(
            "SELECT * FROM sessions WHERE project_id = %s ORDER BY created_at, id", (project_id,)
        )
        return [_session(r) for r in rows]


# --- jobs ---------------------------------------------------------------------------------------


def _job(row: Row) -> Job:
    return Job(
        id=row["id"],
        project_id=row["project_id"],
        job_type=JobType(row["job_type"]),
        created_by=row["created_by"],
        device_id=row["device_id"],
        status=JobStatus(row["status"]),
        input_reference=row["input_reference"],
        output_reference=row["output_reference"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        error_summary=row["error_summary"],
    )


_JOB_INSERT = (
    "INSERT INTO jobs (id, project_id, job_type, created_by, device_id, status, input_reference,"
    " output_reference, created_at, started_at, completed_at, error_summary)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


class PostgresJobRepository(_Repo):
    @staticmethod
    def _params(job: Job) -> tuple[object, ...]:
        return (
            job.id,
            job.project_id,
            job.job_type.value,
            job.created_by,
            job.device_id,
            job.status.value,
            job.input_reference,
            job.output_reference,
            job.created_at,
            job.started_at,
            job.completed_at,
            job.error_summary,
        )

    def add(self, job: Job) -> None:
        self._exec(_JOB_INSERT, self._params(job))

    def save(self, job: Job) -> None:
        self._exec(
            _JOB_INSERT + " ON CONFLICT (id) DO UPDATE SET"
            " device_id = EXCLUDED.device_id, status = EXCLUDED.status,"
            " input_reference = EXCLUDED.input_reference,"
            " output_reference = EXCLUDED.output_reference, started_at = EXCLUDED.started_at,"
            " completed_at = EXCLUDED.completed_at, error_summary = EXCLUDED.error_summary",
            self._params(job),
        )

    def get(self, job_id: str) -> Job | None:
        row = self._one("SELECT * FROM jobs WHERE id = %s", (job_id,))
        return _job(row) if row else None


# --- device commands ----------------------------------------------------------------------------


def _command(row: Row) -> DeviceCommand:
    return DeviceCommand(
        id=row["id"],
        project_id=row["project_id"],
        device_id=row["device_id"],
        name=row["name"],
        requested_by=row["requested_by"],
        args=dict(row["args"]),
        status=CommandStatus(row["status"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        sent_at=row["sent_at"],
        completed_at=row["completed_at"],
        detail=row["detail"],
        output=dict(row["output"]),
    )


_COMMAND_INSERT = (
    "INSERT INTO device_commands (id, project_id, device_id, name, requested_by, args, status,"
    " created_at, expires_at, sent_at, completed_at, detail, output)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)

_PENDING = tuple(s.value for s in CommandStatus if s.is_pending)


class PostgresDeviceCommandRepository(_Repo):
    @staticmethod
    def _params(command: DeviceCommand) -> tuple[object, ...]:
        return (
            command.id,
            command.project_id,
            command.device_id,
            command.name,
            command.requested_by,
            Jsonb(command.args),
            command.status.value,
            command.created_at,
            command.expires_at,
            command.sent_at,
            command.completed_at,
            command.detail,
            Jsonb(command.output),
        )

    def add(self, command: DeviceCommand) -> None:
        self._exec(_COMMAND_INSERT, self._params(command))

    def save(self, command: DeviceCommand) -> None:
        self._exec(
            _COMMAND_INSERT + " ON CONFLICT (id) DO UPDATE SET"
            " status = EXCLUDED.status, expires_at = EXCLUDED.expires_at,"
            " sent_at = EXCLUDED.sent_at, completed_at = EXCLUDED.completed_at,"
            " detail = EXCLUDED.detail, output = EXCLUDED.output",
            self._params(command),
        )

    def get(self, command_id: str) -> DeviceCommand | None:
        row = self._one("SELECT * FROM device_commands WHERE id = %s", (command_id,))
        return _command(row) if row else None

    def count_pending(self, device_id: str) -> int:
        row = self._one(
            "SELECT count(*) AS n FROM device_commands WHERE device_id = %s AND status = ANY(%s)",
            (device_id, list(_PENDING)),
        )
        return int(row["n"]) if row else 0


# --- ingest -------------------------------------------------------------------------------------


class PostgresProcessedMessageStore(_Repo):
    def mark_processed(self, key: str) -> bool:
        inserted = self._exec(
            "INSERT INTO processed_messages (key) VALUES (%s) ON CONFLICT (key) DO NOTHING",
            (key,),
        )
        return inserted == 1


class PostgresSequenceTracker(_Repo):
    def observe(self, device_id: str, sequence_number: int) -> int:
        with self._pool.connection() as conn:
            # Insert-or-lock: the row lock serialises concurrent observers of one device.
            inserted = conn.execute(
                "INSERT INTO device_sequences (device_id, last_sequence) VALUES (%s, %s)"
                " ON CONFLICT (device_id) DO NOTHING",
                (device_id, sequence_number),
            ).rowcount
            if inserted == 1:
                return 0  # first message from this device
            row = conn.execute(
                "SELECT last_sequence FROM device_sequences WHERE device_id = %s FOR UPDATE",
                (device_id,),
            ).fetchone()
            last = int(row[0]) if row else -1
            if sequence_number <= last:
                return 0  # duplicate or out of order
            conn.execute(
                "UPDATE device_sequences SET last_sequence = %s, updated_at = now()"
                " WHERE device_id = %s",
                (sequence_number, device_id),
            )
            return sequence_number - last - 1


class PostgresRawMessageStore(_Repo):
    def put(self, *, device_id: str, message_id: str, received_at: datetime, body: bytes) -> None:
        self._exec(
            "INSERT INTO raw_device_messages"
            " (device_id, message_id, received_at, size_bytes, sha256, body)"
            " VALUES (%s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (device_id, message_id) DO NOTHING",
            (device_id, message_id, received_at, len(body), hashlib.sha256(body).hexdigest(), body),
        )

    def quarantine(
        self, *, device_id: str | None, received_at: datetime, body: bytes, reason: str
    ) -> None:
        self._exec(
            "INSERT INTO quarantined_device_messages"
            " (device_id, received_at, reason, size_bytes, sha256, body)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (device_id, received_at, reason, len(body), hashlib.sha256(body).hexdigest(), body),
        )


class PostgresTelemetryRepository(_Repo):
    def add_telemetry(
        self, *, device_id: str, message_id: str, at: datetime, metrics: dict[str, object]
    ) -> None:
        self._exec(
            "INSERT INTO device_telemetry (device_id, message_id, at, metrics)"
            " VALUES (%s, %s, %s, %s)",
            (device_id, message_id, at, Jsonb(metrics)),
        )

    def add_log(
        self, *, device_id: str, message_id: str, at: datetime, level: str, message: str
    ) -> None:
        self._exec(
            "INSERT INTO device_logs (device_id, message_id, at, level, message)"
            " VALUES (%s, %s, %s, %s, %s)",
            (device_id, message_id, at, level, message),
        )

    def add_event(
        self,
        *,
        device_id: str,
        message_id: str | None,
        at: datetime,
        name: str,
        severity: str,
        detail: str | None,
    ) -> None:
        self._exec(
            "INSERT INTO device_events (device_id, message_id, at, name, severity, detail)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (device_id, message_id, at, name, severity, detail),
        )

    def recent_telemetry(self, device_id: str, *, limit: int) -> list[TelemetrySample]:
        if limit <= 0:
            return []
        rows = self._all(
            "SELECT at, metrics FROM ("
            "  SELECT id, at, metrics FROM device_telemetry WHERE device_id = %s"
            "  ORDER BY at DESC, id DESC LIMIT %s"
            ") newest ORDER BY at, id",
            (device_id, limit),
        )
        return [TelemetrySample(at=r["at"], readings=dict(r["metrics"])) for r in rows]

    def recent_logs(self, device_id: str, *, limit: int) -> list[DeviceLogEntry]:
        """Log lines and device events merged, as ``DeviceLogEntry`` explains."""
        if limit <= 0:
            return []
        rows = self._all(
            "SELECT at, kind, level, message FROM ("
            "  SELECT id, at, 'log' AS kind, level, message, 0 AS src"
            "    FROM device_logs WHERE device_id = %s"
            "  UNION ALL"
            "  SELECT id, at, 'event' AS kind, severity AS level,"
            "         name || COALESCE(': ' || NULLIF(detail, ''), '') AS message, 1 AS src"
            "    FROM device_events WHERE device_id = %s"
            "  ORDER BY at DESC, src DESC, id DESC LIMIT %s"
            ") newest ORDER BY at, src, id",
            (device_id, device_id, limit),
        )
        return [
            DeviceLogEntry(at=r["at"], kind=r["kind"], level=r["level"], message=r["message"])
            for r in rows
        ]
