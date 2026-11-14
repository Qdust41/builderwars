"""HTTP request/response models. Kept separate from domain models on purpose."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from application.realtime import RealtimeEventType
from application.services import ProjectMember
from domain.devices import CommandStatus, ConnectionStatus, Device, DeviceCommand
from domain.jobs import Job, JobStatus, JobType
from domain.projects import Project, ProjectRole
from domain.sessions import Session, SessionStatus


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthOut(BaseModel):
    status: str
    environment: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectOut(_Out):
    id: str
    name: str
    owner_user_id: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, p: Project) -> ProjectOut:
        return cls.model_validate(p)


class MemberAdd(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")
    # Ownership is never granted here; only the owner may grant admin.
    role: Literal[ProjectRole.ADMIN, ProjectRole.MEMBER, ProjectRole.VIEWER] = ProjectRole.MEMBER


class MemberOut(BaseModel):
    user_id: str
    email: str | None
    role: ProjectRole
    created_at: datetime

    @classmethod
    def of(cls, m: ProjectMember) -> MemberOut:
        ms = m.membership
        return cls(user_id=ms.user_id, email=m.email, role=ms.role, created_at=ms.created_at)


class DeviceCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    hardware_model: str = Field(default="freewili-1-og", min_length=1, max_length=64)
    extensions: list[str] = Field(default_factory=lambda: ["bottlenose-wifi-orca"], max_length=8)


class DeviceOut(_Out):
    id: str
    project_id: str
    display_name: str
    hardware_model: str
    extensions: list[str]
    firmware_version: str | None
    connection_status: ConnectionStatus
    last_seen_at: datetime | None
    created_at: datetime

    @field_validator("extensions", mode="before")
    @classmethod
    def _sorted(cls, value: object) -> object:
        return sorted(value) if isinstance(value, set | frozenset) else value

    @classmethod
    def of(cls, d: Device) -> DeviceOut:
        return cls.model_validate(d)


class DeviceStatusOut(BaseModel):
    device_id: str
    connection_status: ConnectionStatus
    firmware_version: str | None
    last_seen_at: datetime | None


class SessionCreate(BaseModel):
    device_id: str | None = None


class SessionOut(_Out):
    id: str
    project_id: str
    device_id: str | None
    created_by: str
    status: SessionStatus
    created_at: datetime

    @classmethod
    def of(cls, s: Session) -> SessionOut:
        return cls.model_validate(s)


class SessionChannelOut(BaseModel):
    session_id: str
    channel: str
    event_types: list[RealtimeEventType]


class DeviceChannelOut(BaseModel):
    device_id: str
    channel: str
    event_types: list[RealtimeEventType]


TelemetryValue = float | int | bool | str


class TelemetrySampleOut(BaseModel):
    ts: datetime
    readings: dict[str, TelemetryValue]


class DeviceLogEntryOut(BaseModel):
    at: datetime
    kind: Literal["log", "event"]
    level: str
    message: str


class JobCreate(BaseModel):
    job_type: JobType
    device_id: str | None = None
    input_reference: str | None = Field(default=None, max_length=1024)


class JobOut(_Out):
    id: str
    project_id: str
    device_id: str | None
    job_type: JobType
    status: JobStatus
    input_reference: str | None
    output_reference: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_summary: str | None

    @classmethod
    def of(cls, j: Job) -> JobOut:
        return cls.model_validate(j)


CommandArg = float | int | bool | str


class CommandCreate(BaseModel):
    """Same naming rules as the protocol's ``CommandPayload``; the host's allowlist decides."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    args: dict[str, CommandArg] = Field(default_factory=dict, max_length=32)


class CommandOut(_Out):
    id: str
    project_id: str
    device_id: str
    name: str
    args: dict[str, CommandArg]
    requested_by: str
    status: CommandStatus
    created_at: datetime
    expires_at: datetime | None
    sent_at: datetime | None
    completed_at: datetime | None
    detail: str | None
    output: dict[str, CommandArg]

    @classmethod
    def of(cls, c: DeviceCommand) -> CommandOut:
        return cls.model_validate(c)
