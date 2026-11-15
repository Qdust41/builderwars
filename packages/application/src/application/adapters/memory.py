"""IN-MEMORY ADAPTERS — LOCAL DEVELOPMENT AND TESTS ONLY.

State is per-process and lost on restart. The API refuses to start with these adapters unless
``APP_ENV`` is ``local`` or ``test`` (see ``api.dependencies``), so they can never be silently
used in a deployed environment.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import cast

from application.ports import (
    AutoFixSecrets,
    DeviceLogEntry,
    DeviceLogRecord,
    LogPosition,
    TelemetrySample,
)
from application.realtime import RealtimeEvent
from device_protocol import DeviceEnvelope
from domain.autofix import AutoFixRun, AutoFixSettings
from domain.common import ConflictError
from domain.devices import Device, DeviceCommand, DeviceSetup, Sensor, TargetBoard
from domain.jobs import Job
from domain.projects import Project, ProjectMembership
from domain.sessions import Session
from domain.users import User, normalize_email


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._items: dict[str, Project] = {}

    def add(self, project: Project) -> None:
        self._items[project.id] = project

    def get(self, project_id: str) -> Project | None:
        return self._items.get(project_id)

    def list_by_ids(self, project_ids: Sequence[str]) -> list[Project]:
        return [self._items[i] for i in project_ids if i in self._items]


class InMemoryMembershipRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], ProjectMembership] = {}

    def add(self, membership: ProjectMembership) -> None:
        self._items[(membership.project_id, membership.user_id)] = membership

    def get(self, project_id: str, user_id: str) -> ProjectMembership | None:
        return self._items.get((project_id, user_id))

    def list_for_user(self, user_id: str) -> list[ProjectMembership]:
        return [m for m in self._items.values() if m.user_id == user_id]

    def list_for_project(self, project_id: str) -> list[ProjectMembership]:
        return [m for m in self._items.values() if m.project_id == project_id]

    def remove(self, project_id: str, user_id: str) -> None:
        self._items.pop((project_id, user_id), None)


class InMemoryUserDirectory:
    """Local stand-in for the Cognito user pool. ``add`` is how tests and dev mode seed it."""

    def __init__(self) -> None:
        self._by_id: dict[str, User] = {}

    def add(self, user: User) -> None:
        self._by_id[user.user_id] = user

    def find_by_email(self, email: str) -> User | None:
        wanted = normalize_email(email)
        return next((u for u in self._by_id.values() if normalize_email(u.email) == wanted), None)

    def get(self, user_id: str) -> User | None:
        return self._by_id.get(user_id)


class InMemoryDeviceRepository:
    def __init__(self) -> None:
        self._items: dict[str, Device] = {}

    def add(self, device: Device) -> None:
        self._items[device.id] = device

    def save(self, device: Device) -> None:
        self._items[device.id] = device

    def get(self, device_id: str) -> Device | None:
        return self._items.get(device_id)

    def list_for_project(self, project_id: str) -> list[Device]:
        return [d for d in self._items.values() if d.project_id == project_id]


class InMemoryDeviceSetupRepository:
    def __init__(self) -> None:
        self._items: dict[str, DeviceSetup] = {}

    def get(self, device_id: str) -> DeviceSetup | None:
        return self._items.get(device_id)

    def save(self, setup: DeviceSetup) -> None:
        self._items[setup.device_id] = setup


class InMemoryTargetBoardRepository:
    """``sensors`` (optional) mirrors the database's ON DELETE CASCADE."""

    def __init__(self, sensors: InMemorySensorRepository | None = None) -> None:
        self._items: dict[str, TargetBoard] = {}
        self._sensors = sensors

    def list_for_device(self, device_id: str) -> list[TargetBoard]:
        found = [b for b in self._items.values() if b.device_id == device_id]
        return sorted(found, key=lambda b: (b.created_at, b.id))

    def get(self, board_id: str) -> TargetBoard | None:
        return self._items.get(board_id)

    def add(self, board: TargetBoard) -> None:
        self._items[board.id] = board

    def save(self, board: TargetBoard) -> None:
        self._items[board.id] = board

    def delete(self, board_id: str) -> None:
        self._items.pop(board_id, None)
        if self._sensors is not None:
            self._sensors.delete_for_board(board_id)


class InMemorySensorRepository:
    def __init__(self) -> None:
        self._items: dict[str, Sensor] = {}

    def delete_for_board(self, board_id: str) -> None:
        for sensor_id in [s.id for s in self._items.values() if s.board_id == board_id]:
            del self._items[sensor_id]

    def list_for_device(self, device_id: str) -> list[Sensor]:
        found = [s for s in self._items.values() if s.device_id == device_id]
        return sorted(found, key=lambda s: (s.created_at, s.id))

    def get(self, sensor_id: str) -> Sensor | None:
        return self._items.get(sensor_id)

    def _check_key(self, sensor: Sensor) -> None:
        for other in self._items.values():
            if (
                other.id != sensor.id
                and other.device_id == sensor.device_id
                and other.key == sensor.key
            ):
                raise ConflictError(f"this device already has a sensor named {sensor.key!r}")

    def add(self, sensor: Sensor) -> None:
        self._check_key(sensor)
        self._items[sensor.id] = sensor

    def save(self, sensor: Sensor) -> None:
        self._check_key(sensor)
        self._items[sensor.id] = sensor

    def delete(self, sensor_id: str) -> None:
        self._items.pop(sensor_id, None)


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._items: dict[str, Session] = {}

    def add(self, session: Session) -> None:
        self._items[session.id] = session

    def get(self, session_id: str) -> Session | None:
        return self._items.get(session_id)

    def list_for_project(self, project_id: str) -> list[Session]:
        return [s for s in self._items.values() if s.project_id == project_id]


class InMemoryJobRepository:
    def __init__(self) -> None:
        self._items: dict[str, Job] = {}

    def add(self, job: Job) -> None:
        self._items[job.id] = job

    def save(self, job: Job) -> None:
        self._items[job.id] = job

    def get(self, job_id: str) -> Job | None:
        return self._items.get(job_id)


class InMemoryProcessedMessageStore:
    def __init__(self) -> None:
        self._keys: set[str] = set()
        self._lock = threading.Lock()

    def mark_processed(self, key: str) -> bool:
        with self._lock:
            if key in self._keys:
                return False
            self._keys.add(key)
            return True


@dataclass
class InMemoryRawMessageStore:
    items: list[tuple[str, str, datetime, bytes]] = field(default_factory=list)
    quarantined: list[tuple[str | None, datetime, bytes, str]] = field(default_factory=list)

    def put(self, *, device_id: str, message_id: str, received_at: datetime, body: bytes) -> None:
        self.items.append((device_id, message_id, received_at, body))

    def quarantine(
        self, *, device_id: str | None, received_at: datetime, body: bytes, reason: str
    ) -> None:
        self.quarantined.append((device_id, received_at, body, reason))


class InMemorySequenceTracker:
    def __init__(self) -> None:
        self._last: dict[str, int] = {}
        self._lock = threading.Lock()

    def observe(self, device_id: str, sequence_number: int) -> int:
        with self._lock:
            last = self._last.get(device_id)
            if last is None or sequence_number > last:
                self._last[device_id] = sequence_number
            if last is None or sequence_number <= last:
                return 0
            return sequence_number - last - 1


class InMemoryDeviceCommandRepository:
    def __init__(self) -> None:
        self._items: dict[str, DeviceCommand] = {}

    def add(self, command: DeviceCommand) -> None:
        self._items[command.id] = command

    def get(self, command_id: str) -> DeviceCommand | None:
        return self._items.get(command_id)

    def save(self, command: DeviceCommand) -> None:
        self._items[command.id] = command

    def count_pending(self, device_id: str) -> int:
        return sum(
            1 for c in self._items.values() if c.device_id == device_id and c.status.is_pending
        )

    def list_pending(self, device_id: str) -> list[DeviceCommand]:
        found = [
            c for c in self._items.values() if c.device_id == device_id and c.status.is_pending
        ]
        return sorted(found, key=lambda c: (c.created_at, c.id))


@dataclass
class InMemoryTelemetryRepository:
    telemetry: list[dict[str, object]] = field(default_factory=list)
    logs: list[dict[str, object]] = field(default_factory=list)
    events: list[dict[str, object]] = field(default_factory=list)

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
        self.events.append(
            {
                "device_id": device_id,
                "message_id": message_id,
                "at": at,
                "name": name,
                "severity": severity,
                "detail": detail,
            }
        )

    def add_telemetry(
        self, *, device_id: str, message_id: str, at: datetime, metrics: dict[str, object]
    ) -> None:
        self.telemetry.append(
            {"device_id": device_id, "message_id": message_id, "at": at, "metrics": metrics}
        )

    def add_log(
        self, *, device_id: str, message_id: str, at: datetime, level: str, message: str
    ) -> None:
        self.logs.append(
            {
                "device_id": device_id,
                "message_id": message_id,
                "at": at,
                "level": level,
                "message": message,
            }
        )

    def recent_telemetry(self, device_id: str, *, limit: int) -> list[TelemetrySample]:
        rows = [r for r in self.telemetry if r["device_id"] == device_id]
        rows.sort(key=lambda r: _at(r))
        return (
            [
                TelemetrySample(at=_at(r), readings=dict(cast(dict[str, object], r["metrics"])))
                for r in rows[-limit:]
            ]
            if limit > 0
            else []
        )

    def recent_logs(self, device_id: str, *, limit: int) -> list[DeviceLogEntry]:
        entries = [
            DeviceLogEntry(at=_at(r), kind="log", level=str(r["level"]), message=str(r["message"]))
            for r in self.logs
            if r["device_id"] == device_id
        ]
        for r in self.events:
            if r["device_id"] != device_id:
                continue
            detail = f": {r['detail']}" if r["detail"] else ""
            entries.append(
                DeviceLogEntry(
                    at=_at(r),
                    kind="event",
                    level=str(r["severity"]),
                    message=f"{r['name']}{detail}",
                )
            )
        entries.sort(key=lambda e: e.at)
        return entries[-limit:] if limit > 0 else []

    def log_history(
        self,
        device_id: str,
        *,
        since: datetime | None,
        until: datetime | None,
        after: LogPosition | None,
        limit: int,
    ) -> list[DeviceLogRecord]:
        records = [
            DeviceLogRecord(
                at=_at(r),
                kind="log",
                level=str(r["level"]),
                message=str(r["message"]),
                message_id=cast(str | None, r["message_id"]),
                source=0,
                row_id=i,
            )
            for i, r in enumerate(self.logs)
            if r["device_id"] == device_id
        ]
        for i, r in enumerate(self.events):
            if r["device_id"] != device_id:
                continue
            detail = f": {r['detail']}" if r["detail"] else ""
            records.append(
                DeviceLogRecord(
                    at=_at(r),
                    kind="event",
                    level=str(r["severity"]),
                    message=f"{r['name']}{detail}",
                    message_id=cast(str | None, r["message_id"]),
                    source=1,
                    row_id=i,
                )
            )

        def key(record: DeviceLogRecord | LogPosition) -> tuple[datetime, int, int]:
            return (record.at, record.source, record.row_id)

        records = [
            r
            for r in records
            if (since is None or r.at >= since)
            and (until is None or r.at < until)
            and (after is None or key(r) > key(after))
        ]
        records.sort(key=key)
        return records[: max(0, limit)]


def _at(row: dict[str, object]) -> datetime:
    return cast(datetime, row["at"])


@dataclass
class InMemoryJobQueue:
    job_ids: list[str] = field(default_factory=list)

    def enqueue(self, job_id: str) -> None:
        self.job_ids.append(job_id)


@dataclass
class InMemoryCommandQueue:
    command_ids: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def enqueue_command(self, command_id: str) -> None:
        with self._lock:
            self.command_ids.append(command_id)

    def take(self, predicate: Callable[[str], bool]) -> list[str]:
        """Remove and return the queued ids matching ``predicate``, in FIFO order."""
        with self._lock:
            taken = [cid for cid in self.command_ids if predicate(cid)]
            self.command_ids[:] = [cid for cid in self.command_ids if cid not in taken]
            return taken


@dataclass
class RecordingRealtimePublisher:
    """Collects events instead of publishing them; lets tests and local dev inspect them."""

    events: list[RealtimeEvent] = field(default_factory=list)

    def publish(self, event: RealtimeEvent) -> None:
        self.events.append(event)


@dataclass
class RecordingCommandPublisher:
    commands: list[DeviceEnvelope] = field(default_factory=list)

    def publish_command(self, envelope: DeviceEnvelope) -> None:
        self.commands.append(envelope)


class InMemoryAutoFixSettingsRepository:
    def __init__(self) -> None:
        self._items: dict[str, AutoFixSettings] = {}

    def get(self, project_id: str) -> AutoFixSettings | None:
        return self._items.get(project_id)

    def save(self, settings: AutoFixSettings) -> None:
        self._items[settings.project_id] = settings

    def delete(self, project_id: str) -> None:
        self._items.pop(project_id, None)


class InMemoryAutoFixRunRepository:
    def __init__(self) -> None:
        self._items: dict[str, AutoFixRun] = {}
        self._signatures: dict[tuple[str, str], datetime] = {}
        self._lock = threading.Lock()

    def add(self, run: AutoFixRun) -> None:
        self._items[run.id] = run

    def save(self, run: AutoFixRun) -> None:
        self._items[run.id] = run

    def get(self, run_id: str) -> AutoFixRun | None:
        return self._items.get(run_id)

    def list_for_project(self, project_id: str, *, limit: int) -> list[AutoFixRun]:
        runs = [r for r in self._items.values() if r.project_id == project_id]
        runs.sort(key=lambda r: (r.created_at, r.id), reverse=True)
        return runs[:limit]

    def count_since(self, project_id: str, since: datetime) -> int:
        return sum(
            1 for r in self._items.values() if r.project_id == project_id and r.created_at >= since
        )

    def claim_signature(
        self, project_id: str, signature: str, *, now: datetime, window: timedelta
    ) -> bool:
        with self._lock:
            last = self._signatures.get((project_id, signature))
            if last is not None and last > now - window:
                return False
            self._signatures[(project_id, signature)] = now
            return True


class InMemoryAutoFixSecretStore:
    """LOCAL/TEST ONLY: keys held in process memory."""

    def __init__(self) -> None:
        self._items: dict[str, AutoFixSecrets] = {}

    def get(self, project_id: str) -> AutoFixSecrets:
        return self._items.get(project_id, AutoFixSecrets())

    def put(self, project_id: str, secrets: AutoFixSecrets) -> None:
        self._items[project_id] = secrets

    def delete(self, project_id: str) -> None:
        self._items.pop(project_id, None)


@dataclass
class InMemoryAutoFixQueue:
    run_ids: list[str] = field(default_factory=list)

    def enqueue_autofix(self, run_id: str) -> None:
        self.run_ids.append(run_id)
