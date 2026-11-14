"""Payload schemas for each message type.

These are PROVISIONAL until the board hardware and firmware capabilities are confirmed
(see docs/open-decisions.md). They exist so both sides validate the same shape today.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from device_protocol.envelopes import MessageType

MetricValue = float | int | bool | str


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TelemetryPayload(BaseModel):
    """Flat map of metric name -> scalar value, e.g. ``{"temperature_c": 42.5}``.

    Extra keys are the metrics themselves, so unknown keys are allowed but values must be scalars.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    def metrics(self) -> dict[str, MetricValue]:
        extra = self.model_extra or {}
        return dict(extra)

    @classmethod
    def validate_metrics(cls, data: dict[str, Any]) -> TelemetryPayload:
        if not data:
            raise ValueError("telemetry payload must contain at least one metric")
        for key, value in data.items():
            if not isinstance(key, str) or not key:
                raise ValueError("metric names must be non-empty strings")
            if not isinstance(value, MetricValue):
                raise ValueError(f"metric {key!r} must be a scalar, got {type(value).__name__}")
        return cls.model_validate(data)


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogPayload(_Payload):
    level: LogLevel
    message: str = Field(max_length=4096)
    logger: str | None = Field(default=None, max_length=128)


class DeviceState(StrEnum):
    BOOTING = "booting"
    ONLINE = "online"
    BUSY = "busy"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"


class StatusPayload(_Payload):
    state: DeviceState
    uptime_s: int | None = Field(default=None, ge=0)
    detail: str | None = Field(default=None, max_length=1024)


class HeartbeatPayload(_Payload):
    uptime_s: int = Field(ge=0)


class CommandPayload(_Payload):
    """Cloud -> device. Commands are named operations from an allowlist on the board.

    There is deliberately no "run arbitrary shell" command.
    """

    command_id: UUID
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    args: dict[str, MetricValue] = Field(default_factory=dict)
    expires_at: AwareDatetime | None = None

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at


class CommandResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"  # unknown command, bad args, expired, not allowed


class CommandResultPayload(_Payload):
    command_id: UUID
    status: CommandResultStatus
    detail: str | None = Field(default=None, max_length=1024)
    output: dict[str, MetricValue] = Field(default_factory=dict)


PAYLOAD_MODELS: Final[dict[MessageType, type[BaseModel]]] = {
    MessageType.TELEMETRY: TelemetryPayload,
    MessageType.LOG: LogPayload,
    MessageType.STATUS: StatusPayload,
    MessageType.HEARTBEAT: HeartbeatPayload,
    MessageType.COMMAND: CommandPayload,
    MessageType.COMMAND_RESULT: CommandResultPayload,
}


def validate_payload(message_type: MessageType, payload: dict[str, Any]) -> BaseModel:
    if message_type is MessageType.TELEMETRY:
        return TelemetryPayload.validate_metrics(payload)
    return PAYLOAD_MODELS[message_type].model_validate(payload)
