"""HTTP request/response models. Kept separate from domain models on purpose."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from application.realtime import RealtimeEventType
from application.services import MAX_MESSAGES_PER_UPLOAD, IngestOutcome, ProjectMember
from application.services.device_setup import SetupView, sensor_spec
from device_protocol.sensors import SensorProtocol, SensorSpec
from device_protocol.setup import BridgeReport, HostReport
from domain.autofix import (
    DEFAULT_DEDUPE_HOURS,
    DEFAULT_MAX_RUNS_PER_DAY,
    AutoFixLevel,
    AutoFixRun,
    AutoFixRunStatus,
    AutoFixSettings,
    AutoFixTriggerKind,
)
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
        out = cls.model_validate(d)
        # A device that went silent reads as offline (domain.devices.STALE_AFTER).
        return out.model_copy(update={"connection_status": d.status_at(datetime.now(UTC))})


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
    run_id: str | None = Field(
        default=None,
        max_length=64,
        description="The live ``builderwars run`` sending these (keeps its lock on the board; "
        "409 run_superseded if another run took the board over). Omit for saved-data uploads.",
    )


class DeviceMessageResultOut(BaseModel):
    outcome: IngestOutcome
    message_id: str | None = None
    reason: str | None = None
    detail: str | None = None


class DeviceCommandsClaimOut(BaseModel):
    """Commands waiting for a CLI-connected board, as ``{topic, payload}`` like uploads."""

    messages: list[UploadedDeviceMessage]


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


class DeviceRunOut(BaseModel):
    """The ``builderwars run`` that has locked the board: one run at a time."""

    started_at: datetime
    last_seen_at: datetime
    user_id: str
    user_email: str | None = None
    hostname: str | None = None


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
    run: DeviceRunOut | None = Field(
        default=None, description="The `builderwars run` holding the board right now, if any"
    )

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
            run=DeviceRunOut(
                started_at=setup.run_started_at,
                last_seen_at=setup.run_seen_at,
                user_id=setup.run_by,
                user_email=view.run_by_email,
                hostname=(setup.host or {}).get("hostname"),
            )
            if view.run_active and setup.run_started_at and setup.run_seen_at and setup.run_by
            else None,
        )


# --- auto-fix (ADR 0012) ----------------------------------------------------------------------


class AutoFixSettingsIn(BaseModel):
    """Link an OpenAI-compatible endpoint and a GitHub repository to the project.

    ``llm_api_key`` / ``github_token``: leave out to keep what is stored, ``""`` to clear,
    or a value to replace. They are write-only: responses only say whether each is set.
    """

    model_config = ConfigDict(extra="forbid")

    llm_base_url: str = Field(
        min_length=8,
        max_length=500,
        description="Everything before /chat/completions, e.g. https://api.openai.com/v1",
    )
    llm_model: str = Field(min_length=1, max_length=200)
    github_repo: str = Field(min_length=3, max_length=140, description="owner/name")
    base_branch: str | None = Field(
        default=None, max_length=200, description="Defaults to the repository's default branch"
    )
    enabled: bool = True
    auto_trigger: bool = Field(
        default=True, description="Start runs from uploaded error logs (false: manual only)"
    )
    min_level: AutoFixLevel = AutoFixLevel.ERROR
    max_runs_per_day: int = Field(default=DEFAULT_MAX_RUNS_PER_DAY, ge=1, le=50)
    dedupe_hours: int = Field(default=DEFAULT_DEDUPE_HOURS, ge=1, le=720)
    instructions: str | None = Field(
        default=None,
        max_length=4000,
        description="Notes for the model, e.g. where the board code lives",
    )
    llm_api_key: str | None = Field(default=None, max_length=4000)
    github_token: str | None = Field(default=None, max_length=1000)


class AutoFixSettingsOut(_Out):
    project_id: str
    enabled: bool
    llm_base_url: str
    llm_model: str
    github_repo: str
    base_branch: str | None
    auto_trigger: bool
    min_level: AutoFixLevel
    max_runs_per_day: int
    dedupe_hours: int
    instructions: str | None
    has_llm_api_key: bool
    has_github_token: bool
    ready: bool
    updated_by: str
    updated_at: datetime

    @classmethod
    def of(cls, settings: AutoFixSettings) -> AutoFixSettingsOut:
        return cls.model_validate(settings)


class AutoFixRunCreate(BaseModel):
    """Ask for a fix now. Without ``message``, the device's latest error log is used."""

    model_config = ConfigDict(extra="forbid")

    device_id: str | None = None
    message: str | None = Field(default=None, max_length=4096)
    level: Literal["error", "critical", "warning"] = "error"


class AutoFixRunOut(_Out):
    id: str
    project_id: str
    device_id: str | None
    trigger: AutoFixTriggerKind
    status: AutoFixRunStatus
    error_level: str
    error_message: str
    requested_by: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    model: str | None
    github_repo: str | None
    branch: str | None
    pr_number: int | None
    pr_url: str | None
    summary: str | None
    files_changed: list[str]

    @classmethod
    def of(cls, run: AutoFixRun) -> AutoFixRunOut:
        return cls.model_validate(run)
