from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from domain.devices import Device, DeviceCommand
from domain.jobs import Job
from domain.projects import Project, ProjectMembership
from domain.sessions import Session
from domain.users import User


class ProjectRepository(Protocol):
    def add(self, project: Project) -> None: ...
    def get(self, project_id: str) -> Project | None: ...
    def list_by_ids(self, project_ids: Sequence[str]) -> list[Project]: ...


class MembershipRepository(Protocol):
    def add(self, membership: ProjectMembership) -> None: ...
    def get(self, project_id: str, user_id: str) -> ProjectMembership | None: ...
    def list_for_user(self, user_id: str) -> list[ProjectMembership]: ...
    def list_for_project(self, project_id: str) -> list[ProjectMembership]: ...
    def remove(self, project_id: str, user_id: str) -> None: ...


class UserDirectory(Protocol):
    """Read-only lookup of human accounts. In AWS this is the Cognito user pool."""

    def find_by_email(self, email: str) -> User | None: ...
    def get(self, user_id: str) -> User | None: ...


class DeviceRepository(Protocol):
    def add(self, device: Device) -> None: ...
    def get(self, device_id: str) -> Device | None: ...
    def save(self, device: Device) -> None: ...
    def list_for_project(self, project_id: str) -> list[Device]: ...


class SessionRepository(Protocol):
    def add(self, session: Session) -> None: ...
    def get(self, session_id: str) -> Session | None: ...
    def list_for_project(self, project_id: str) -> list[Session]: ...


class JobRepository(Protocol):
    def add(self, job: Job) -> None: ...
    def get(self, job_id: str) -> Job | None: ...
    def save(self, job: Job) -> None: ...


class ProcessedMessageStore(Protocol):
    """Idempotency record for at-least-once device message delivery.

    ``mark_processed`` must be atomic: it returns True exactly once per key. In AWS this maps to
    a conditional write (e.g. PostgreSQL ``INSERT ... ON CONFLICT DO NOTHING``).
    """

    def mark_processed(self, key: str) -> bool: ...


class RawDeviceMessageStore(Protocol):
    """Raw message retention (S3 ``raw/`` in AWS), kept separate from normalised records.

    Rejected messages are quarantined (S3 ``rejected/``) rather than silently dropped.
    """

    def put(
        self, *, device_id: str, message_id: str, received_at: datetime, body: bytes
    ) -> None: ...

    def quarantine(
        self, *, device_id: str | None, received_at: datetime, body: bytes, reason: str
    ) -> None: ...


class SequenceTracker(Protocol):
    """Remembers the highest ``sequence_number`` seen per device, for gap detection.

    Returns how many numbers were skipped (0 = contiguous, first message, or out of order).
    """

    def observe(self, device_id: str, sequence_number: int) -> int: ...


class DeviceCommandRepository(Protocol):
    def add(self, command: DeviceCommand) -> None: ...
    def get(self, command_id: str) -> DeviceCommand | None: ...
    def save(self, command: DeviceCommand) -> None: ...
    def count_pending(self, device_id: str) -> int: ...


@dataclass(frozen=True, slots=True)
class TelemetrySample:
    """One timestamped set of readings (a telemetry batch holds 1-32 of these)."""

    at: datetime
    readings: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeviceLogEntry:
    """A device log line or event, merged into one stream for display.

    ``kind`` is ``"log"`` (``level`` = log level) or ``"event"`` (``level`` = severity,
    ``message`` = event name plus detail).
    """

    at: datetime
    kind: str
    level: str
    message: str


@dataclass(frozen=True, slots=True)
class DeviceLogRecord:
    """One row of a device's full log history (log lines and events), for export.

    Rows are ordered by ``(at, source, row_id)``: ``source`` is 0 for a log line and 1 for
    an event, ``row_id`` is the storage row id. That triple is the keyset paging cursor.
    """

    at: datetime
    kind: str
    level: str
    message: str
    message_id: str | None
    source: int
    row_id: int

    @property
    def position(self) -> LogPosition:
        return LogPosition(at=self.at, source=self.source, row_id=self.row_id)


@dataclass(frozen=True, slots=True)
class LogPosition:
    """Where a log history page ended; the next page starts strictly after it."""

    at: datetime
    source: int
    row_id: int


class TelemetryRepository(Protocol):
    """Normalised telemetry/log records. Storage choice depends on volume (open decision #6).

    Reads return the newest ``limit`` records, oldest first.
    """

    def recent_telemetry(self, device_id: str, *, limit: int) -> list[TelemetrySample]: ...

    def recent_logs(self, device_id: str, *, limit: int) -> list[DeviceLogEntry]: ...

    def log_history(
        self,
        device_id: str,
        *,
        since: datetime | None,
        until: datetime | None,
        after: LogPosition | None,
        limit: int,
    ) -> list[DeviceLogRecord]:
        """Up to ``limit`` log lines and events oldest first, ``since <= at < until``,
        strictly after ``after``."""
        ...

    def add_telemetry(
        self, *, device_id: str, message_id: str, at: datetime, metrics: dict[str, object]
    ) -> None: ...

    def add_log(
        self, *, device_id: str, message_id: str, at: datetime, level: str, message: str
    ) -> None: ...

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
        """Device-reported events and ingest-derived ones (e.g. ``sequence_gap``)."""
        ...
