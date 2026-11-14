"""HTTP request/response models. Kept separate from domain models on purpose."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from application.realtime import RealtimeEventType
from domain.devices import ConnectionStatus, Device
from domain.jobs import Job, JobStatus, JobType
from domain.projects import Project
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


class DeviceCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    hardware_model: str = Field(min_length=1, max_length=64)


class DeviceOut(_Out):
    id: str
    project_id: str
    display_name: str
    hardware_model: str
    firmware_version: str | None
    connection_status: ConnectionStatus
    last_seen_at: datetime | None
    created_at: datetime

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
