from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from domain.devices import Device
from domain.jobs import Job
from domain.projects import Project, ProjectMembership
from domain.sessions import Session


class ProjectRepository(Protocol):
    def add(self, project: Project) -> None: ...
    def get(self, project_id: str) -> Project | None: ...
    def list_by_ids(self, project_ids: Sequence[str]) -> list[Project]: ...


class MembershipRepository(Protocol):
    def add(self, membership: ProjectMembership) -> None: ...
    def get(self, project_id: str, user_id: str) -> ProjectMembership | None: ...
    def list_for_user(self, user_id: str) -> list[ProjectMembership]: ...


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
    """Raw message retention (S3 in AWS), kept separate from normalised records."""

    def put(
        self, *, device_id: str, message_id: str, received_at: datetime, body: bytes
    ) -> None: ...


class TelemetryRepository(Protocol):
    """Normalised telemetry/log records. Storage choice depends on volume (open decision #6)."""

    def add_telemetry(
        self, *, device_id: str, message_id: str, at: datetime, metrics: dict[str, object]
    ) -> None: ...

    def add_log(
        self, *, device_id: str, message_id: str, at: datetime, level: str, message: str
    ) -> None: ...
