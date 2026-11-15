"""PostgreSQL implementations of the repository ports (``application.ports.repositories``).

Each method runs in its own short transaction on a pooled connection. Multi-statement
atomicity across repositories (an outbox, say) is out of scope here; see workstream G.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from application.ports import DeviceLogEntry, DeviceLogRecord, LogPosition, TelemetrySample
from domain.autofix import (
    AutoFixLevel,
    AutoFixRun,
    AutoFixRunStatus,
    AutoFixSettings,
    AutoFixTriggerKind,
)
from domain.common import ConflictError
from domain.devices import (
    CommandStatus,
    ConnectionStatus,
    Device,
    DeviceCommand,
    DeviceSetup,
    Sensor,
    TargetBoard,
)
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


# --- device setup and sensors -------------------------------------------------------------------


def _setup(row: Row) -> DeviceSetup:
    return DeviceSetup(
        device_id=row["device_id"],
        host=row["host"],
        bridge=row["bridge"],
        reported_at=row["reported_at"],
        reported_by=row["reported_by"],
        updated_at=row["updated_at"],
        run_id=row["run_id"],
        run_by=row["run_by"],
        run_started_at=row["run_started_at"],
        run_seen_at=row["run_seen_at"],
    )


class PostgresDeviceSetupRepository(_Repo):
    def get(self, device_id: str) -> DeviceSetup | None:
        row = self._one("SELECT * FROM device_setups WHERE device_id = %s", (device_id,))
        return _setup(row) if row else None

    def save(self, setup: DeviceSetup) -> None:
        self._exec(
            "INSERT INTO device_setups (device_id, host, bridge, reported_at, reported_by,"
            " updated_at, run_id, run_by, run_started_at, run_seen_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (device_id) DO UPDATE SET host = EXCLUDED.host,"
            " bridge = EXCLUDED.bridge, reported_at = EXCLUDED.reported_at,"
            " reported_by = EXCLUDED.reported_by, updated_at = EXCLUDED.updated_at,"
            " run_id = EXCLUDED.run_id, run_by = EXCLUDED.run_by,"
            " run_started_at = EXCLUDED.run_started_at, run_seen_at = EXCLUDED.run_seen_at",
            (
                setup.device_id,
                Jsonb(setup.host) if setup.host is not None else None,
                Jsonb(setup.bridge) if setup.bridge is not None else None,
                setup.reported_at,
                setup.reported_by,
                setup.updated_at,
                setup.run_id,
                setup.run_by,
                setup.run_started_at,
                setup.run_seen_at,
            ),
        )


def _board(row: Row) -> TargetBoard:
    return TargetBoard(
        id=row["id"],
        device_id=row["device_id"],
        name=row["name"],
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class PostgresTargetBoardRepository(_Repo):
    def list_for_device(self, device_id: str) -> list[TargetBoard]:
        rows = self._all(
            "SELECT * FROM device_target_boards WHERE device_id = %s ORDER BY created_at, id",
            (device_id,),
        )
        return [_board(r) for r in rows]

    def get(self, board_id: str) -> TargetBoard | None:
        row = self._one("SELECT * FROM device_target_boards WHERE id = %s", (board_id,))
        return _board(row) if row else None

    _UPSERT = (
        "INSERT INTO device_target_boards (id, device_id, name, notes, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, %s, %s)"
    )

    @staticmethod
    def _params(board: TargetBoard) -> tuple[object, ...]:
        return (
            board.id,
            board.device_id,
            board.name,
            board.notes,
            board.created_at,
            board.updated_at,
        )

    def add(self, board: TargetBoard) -> None:
        self._exec(self._UPSERT, self._params(board))

    def save(self, board: TargetBoard) -> None:
        self._exec(
            self._UPSERT + " ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,"
            " notes = EXCLUDED.notes, updated_at = EXCLUDED.updated_at",
            self._params(board),
        )

    def delete(self, board_id: str) -> None:
        self._exec("DELETE FROM device_target_boards WHERE id = %s", (board_id,))


def _sensor(row: Row) -> Sensor:
    return Sensor(
        id=row["id"],
        device_id=row["device_id"],
        board_id=row["board_id"],
        key=row["key"],
        name=row["name"],
        bus=row["bus"],
        decode=row["decode"],
        unit=row["unit"],
        poll_interval_s=float(row["poll_interval_s"]),
        enabled=row["enabled"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class PostgresSensorRepository(_Repo):
    def list_for_device(self, device_id: str) -> list[Sensor]:
        rows = self._all(
            "SELECT * FROM device_sensors WHERE device_id = %s ORDER BY created_at, id",
            (device_id,),
        )
        return [_sensor(r) for r in rows]

    def get(self, sensor_id: str) -> Sensor | None:
        row = self._one("SELECT * FROM device_sensors WHERE id = %s", (sensor_id,))
        return _sensor(row) if row else None

    def _write(self, query: str, sensor: Sensor) -> None:
        try:
            self._exec(
                query,
                (
                    sensor.id,
                    sensor.device_id,
                    sensor.board_id,
                    sensor.key,
                    sensor.name,
                    sensor.protocol,
                    Jsonb(sensor.bus),
                    Jsonb(sensor.decode),
                    sensor.unit,
                    sensor.poll_interval_s,
                    sensor.enabled,
                    sensor.created_at,
                    sensor.updated_at,
                ),
            )
        except pg_errors.UniqueViolation as exc:
            raise ConflictError(f"this device already has a sensor named {sensor.key!r}") from exc

    _INSERT = (
        "INSERT INTO device_sensors (id, device_id, board_id, key, name, protocol, bus, decode,"
        " unit, poll_interval_s, enabled, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )

    def add(self, sensor: Sensor) -> None:
        self._write(self._INSERT, sensor)

    def save(self, sensor: Sensor) -> None:
        self._write(
            self._INSERT
            + " ON CONFLICT (id) DO UPDATE SET board_id = EXCLUDED.board_id, key = EXCLUDED.key,"
            " name = EXCLUDED.name, protocol = EXCLUDED.protocol, bus = EXCLUDED.bus,"
            " decode = EXCLUDED.decode, unit = EXCLUDED.unit,"
            " poll_interval_s = EXCLUDED.poll_interval_s, enabled = EXCLUDED.enabled,"
            " updated_at = EXCLUDED.updated_at",
            sensor,
        )

    def delete(self, sensor_id: str) -> None:
        self._exec("DELETE FROM device_sensors WHERE id = %s", (sensor_id,))


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

    def list_pending(self, device_id: str) -> list[DeviceCommand]:
        rows = self._all(
            "SELECT * FROM device_commands WHERE device_id = %s AND status = ANY(%s)"
            " ORDER BY created_at, id",
            (device_id, list(_PENDING)),
        )
        return [_command(r) for r in rows]


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


#: Keyset page over device_logs + device_events. Each branch filters ``at`` itself so it can
#: use its ``(device_id, at)`` index; the exact ``(at, source, id)`` cursor test runs outside.
_LOG_HISTORY_SQL = """
SELECT id, at, kind, level, message, message_id, source FROM (
    SELECT id, at, 'log' AS kind, level, message, message_id, 0 AS source
      FROM device_logs
     WHERE device_id = %s
       AND (%s::timestamptz IS NULL OR at >= %s)
       AND (%s::timestamptz IS NULL OR at < %s)
    UNION ALL
    SELECT id, at, 'event' AS kind, severity AS level,
           name || COALESCE(': ' || NULLIF(detail, ''), '') AS message,
           message_id, 1 AS source
      FROM device_events
     WHERE device_id = %s
       AND (%s::timestamptz IS NULL OR at >= %s)
       AND (%s::timestamptz IS NULL OR at < %s)
) merged
WHERE %s::bigint IS NULL
   OR (at, source, id) > (%s::timestamptz, %s::int, %s::bigint)
ORDER BY at, source, id
LIMIT %s
"""


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

    def log_history(
        self,
        device_id: str,
        *,
        since: datetime | None,
        until: datetime | None,
        after: LogPosition | None,
        limit: int,
    ) -> list[DeviceLogRecord]:
        """Keyset-paged merge of device_logs and device_events, ordered (at, source, id).

        The time bounds (and the cursor's ``at``) are applied inside each branch so both
        use their ``(device_id, at)`` index; the exact cursor comparison runs outside.
        """
        if limit <= 0:
            return []
        lower = since
        if after is not None and (lower is None or after.at > lower):
            lower = after.at
        bounds = (lower, lower, until, until)
        cursor = (
            (after.row_id, after.at, after.source, after.row_id)
            if after is not None
            else (None, None, None, None)
        )
        rows = self._all(_LOG_HISTORY_SQL, (device_id, *bounds, device_id, *bounds, *cursor, limit))
        return [
            DeviceLogRecord(
                at=r["at"],
                kind=r["kind"],
                level=r["level"],
                message=r["message"],
                message_id=r["message_id"],
                source=int(r["source"]),
                row_id=int(r["id"]),
            )
            for r in rows
        ]


# --- auto-fix (ADR 0012) ------------------------------------------------------------------------


def _autofix_settings(row: Row) -> AutoFixSettings:
    return AutoFixSettings(
        project_id=row["project_id"],
        github_repo=row["github_repo"],
        github_token=row["github_token"],
        updated_by=row["updated_by"],
        enabled=row["enabled"],
        auto_trigger=row["auto_trigger"],
        min_level=AutoFixLevel(row["min_level"]),
        base_branch=row["base_branch"],
        max_runs_per_day=row["max_runs_per_day"],
        dedupe_hours=row["dedupe_hours"],
        instructions=row["instructions"],
        updated_at=row["updated_at"],
    )


class PostgresAutoFixSettingsRepository(_Repo):
    def get(self, project_id: str) -> AutoFixSettings | None:
        row = self._one("SELECT * FROM autofix_settings WHERE project_id = %s", (project_id,))
        return _autofix_settings(row) if row else None

    def save(self, settings: AutoFixSettings) -> None:
        self._exec(
            "INSERT INTO autofix_settings (project_id, github_repo, github_token,"
            " base_branch, enabled, auto_trigger, min_level, max_runs_per_day, dedupe_hours,"
            " instructions, updated_by, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (project_id) DO UPDATE SET"
            " github_repo = EXCLUDED.github_repo, github_token = EXCLUDED.github_token,"
            " base_branch = EXCLUDED.base_branch,"
            " enabled = EXCLUDED.enabled, auto_trigger = EXCLUDED.auto_trigger,"
            " min_level = EXCLUDED.min_level, max_runs_per_day = EXCLUDED.max_runs_per_day,"
            " dedupe_hours = EXCLUDED.dedupe_hours, instructions = EXCLUDED.instructions,"
            " updated_by = EXCLUDED.updated_by, updated_at = EXCLUDED.updated_at",
            (
                settings.project_id,
                settings.github_repo,
                settings.github_token,
                settings.base_branch,
                settings.enabled,
                settings.auto_trigger,
                settings.min_level.value,
                settings.max_runs_per_day,
                settings.dedupe_hours,
                settings.instructions,
                settings.updated_by,
                settings.updated_at,
            ),
        )

    def delete(self, project_id: str) -> None:
        self._exec("DELETE FROM autofix_settings WHERE project_id = %s", (project_id,))


def _autofix_run(row: Row) -> AutoFixRun:
    return AutoFixRun(
        id=row["id"],
        project_id=row["project_id"],
        device_id=row["device_id"],
        trigger=AutoFixTriggerKind(row["trigger"]),
        signature=row["signature"],
        error_level=row["error_level"],
        error_message=row["error_message"],
        requested_by=row["requested_by"],
        status=AutoFixRunStatus(row["status"]),
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        model=row["model"],
        github_repo=row["github_repo"],
        branch=row["branch"],
        pr_number=row["pr_number"],
        pr_url=row["pr_url"],
        summary=row["summary"],
        files_changed=tuple(row["files_changed"] or ()),
    )


_AUTOFIX_RUN_COLUMNS = (
    "id, project_id, device_id, trigger, signature, error_level, error_message, requested_by,"
    " status, created_at, started_at, completed_at, model, github_repo, branch, pr_number,"
    " pr_url, summary, files_changed"
)


class PostgresAutoFixRunRepository(_Repo):
    @staticmethod
    def _params(run: AutoFixRun) -> tuple[object, ...]:
        return (
            run.id,
            run.project_id,
            run.device_id,
            run.trigger.value,
            run.signature,
            run.error_level,
            run.error_message,
            run.requested_by,
            run.status.value,
            run.created_at,
            run.started_at,
            run.completed_at,
            run.model,
            run.github_repo,
            run.branch,
            run.pr_number,
            run.pr_url,
            run.summary,
            list(run.files_changed),
        )

    _INSERT = (
        f"INSERT INTO autofix_runs ({_AUTOFIX_RUN_COLUMNS})"  # noqa: S608 - constant columns
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )

    def add(self, run: AutoFixRun) -> None:
        self._exec(self._INSERT, self._params(run))

    def save(self, run: AutoFixRun) -> None:
        self._exec(
            self._INSERT + " ON CONFLICT (id) DO UPDATE SET"
            " status = EXCLUDED.status, started_at = EXCLUDED.started_at,"
            " completed_at = EXCLUDED.completed_at, model = EXCLUDED.model,"
            " github_repo = EXCLUDED.github_repo, branch = EXCLUDED.branch,"
            " pr_number = EXCLUDED.pr_number, pr_url = EXCLUDED.pr_url,"
            " summary = EXCLUDED.summary, files_changed = EXCLUDED.files_changed",
            self._params(run),
        )

    def get(self, run_id: str) -> AutoFixRun | None:
        row = self._one("SELECT * FROM autofix_runs WHERE id = %s", (run_id,))
        return _autofix_run(row) if row else None

    def list_for_project(self, project_id: str, *, limit: int) -> list[AutoFixRun]:
        rows = self._all(
            "SELECT * FROM autofix_runs WHERE project_id = %s"
            " ORDER BY created_at DESC, id DESC LIMIT %s",
            (project_id, limit),
        )
        return [_autofix_run(r) for r in rows]

    def count_since(self, project_id: str, since: datetime) -> int:
        row = self._one(
            "SELECT count(*) AS n FROM autofix_runs WHERE project_id = %s AND created_at >= %s",
            (project_id, since),
        )
        return int(row["n"]) if row else 0

    def claim_signature(
        self, project_id: str, signature: str, *, now: datetime, window: timedelta
    ) -> bool:
        row = self._one(
            "INSERT INTO autofix_signatures (project_id, signature, last_run_at)"
            " VALUES (%s, %s, %s)"
            " ON CONFLICT (project_id, signature) DO UPDATE SET last_run_at = EXCLUDED.last_run_at"
            " WHERE autofix_signatures.last_run_at <= %s"
            " RETURNING 1 AS claimed",
            (project_id, signature, now, now - window),
        )
        return row is not None
