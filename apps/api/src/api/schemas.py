"""HTTP request/response models. Kept separate from domain models on purpose."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from application.realtime import RealtimeEventType
from application.services import MAX_MESSAGES_PER_UPLOAD, IngestOutcome, ProjectMember
from application.services.device_setup import SetupView, sensor_spec
from device_protocol.sensors import SensorProtocol, SensorSpec
from device_protocol.setup import BridgeReport, HostReport
from domain.devices import (
    MAX_TARGET_BOARDS,
    CommandStatus,
    ConnectionStatus,
    Device,
    DeviceCommand,
    Sensor,
    TargetBoard,
)
from domain.jobs import Job, JobStatus, JobType
from domain.projects import Project, ProjectRole
from domain.sessions import Session, SessionStatus


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthOut(BaseModel):
    status: str
    environment: str


# Any signed-in account may create a project and becomes its owner (ADR 0005).
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("project name must not be blank")
        return stripped


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


class UploadedDeviceMessage(BaseModel):
    """One protocol message as the board would publish it: the MQTT topic and the envelope."""

    topic: str = Field(min_length=1, max_length=256)
    payload: dict[str, Any]


class DeviceMessagesUpload(BaseModel):
    messages: list[UploadedDeviceMessage] = Field(min_length=1, max_length=MAX_MESSAGES_PER_UPLOAD)


class DeviceMessageResultOut(BaseModel):
    outcome: IngestOutcome
    message_id: str | None = None
    reason: str | None = None
    detail: str | None = None


class DeviceMessagesUploadOut(BaseModel):
    processed: int
    duplicate: int
    rejected: int
    results: list[DeviceMessageResultOut]


class ClientConfigOut(BaseModel):
    """Public sign-in settings for command-line clients (no secrets: ids only)."""

    environment: str
    auth_mode: Literal["cognito", "dev-header"]
    cognito_region: str | None = None
    cognito_user_pool_id: str | None = None
    cognito_app_client_id: str | None = None


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


class DeviceLogRecordOut(DeviceLogEntryOut):
    #: The device message that carried this line; null for ingest-derived events.
    message_id: str | None


class DeviceLogHistoryOut(BaseModel):
    entries: list[DeviceLogRecordOut]
    #: Pass as ``cursor`` to get the next page; null when there are no more entries.
    next_cursor: str | None


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


# --- test setup: laptop -> FREE-WILi -> up to 4 target boards, and their sensors -------------


class SensorIn(SensorSpec):
    """A sensor definition from the web app, on one of the device's target boards. Unlike
    the shared ``SensorSpec`` (which the CLI reads leniently), unknown fields are an error."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    board_id: str = Field(min_length=1, max_length=80)


class SensorOut(SensorSpec):
    id: str
    device_id: str
    board_id: str
    protocol: SensorProtocol  # same as bus.protocol, for listing
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, sensor: Sensor) -> SensorOut:
        return cls.model_validate(
            {
                **sensor_spec(sensor).model_dump(mode="json"),
                "id": sensor.id,
                "device_id": sensor.device_id,
                "board_id": sensor.board_id,
                "protocol": sensor.protocol,
                "created_at": sensor.created_at,
                "updated_at": sensor.updated_at,
            }
        )


class TargetBoardIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("board name must not be blank")
        return stripped


class TargetBoardOut(_Out):
    id: str
    device_id: str
    name: str
    notes: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, board: TargetBoard) -> TargetBoardOut:
        return cls.model_validate(board)


class DeviceSetupOut(BaseModel):
    """The whole chain for the device page. ``host``/``bridge`` are null until the CLI has
    run against this device; ``bridge`` is also null for a ``--simulate`` run."""

    device_id: str
    host: HostReport | None
    bridge: BridgeReport | None
    reported_at: datetime | None
    max_boards: int
    boards: list[TargetBoardOut]
    sensors: list[SensorOut]

    @classmethod
    def of(cls, view: SetupView) -> DeviceSetupOut:
        setup = view.setup
        return cls(
            device_id=setup.device_id,
            host=HostReport.model_validate(setup.host) if setup.host else None,
            bridge=BridgeReport.model_validate(setup.bridge) if setup.bridge else None,
            reported_at=setup.reported_at,
            max_boards=MAX_TARGET_BOARDS,
            boards=[TargetBoardOut.of(b) for b in view.boards],
            sensors=[SensorOut.of(s) for s in view.sensors],
        )
