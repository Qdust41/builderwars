"""Payload schemas for each message type.

Shapes follow docs/open-decisions.md (2026-11-14). Sensor names inside telemetry readings stay
free-form until the board I/O spec (spec 02) pins them down.
"""

from __future__ import annotations

import itertools
import re
from datetime import datetime
from typing import Any, Final, Union
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from device_protocol.compat import StrEnum
from device_protocol.envelopes import MessageType

# Union[...] rather than "|": isinstance() needs a runtime union object on Python 3.10 too.
MetricValue = Union[float, int, bool, str]  # noqa: UP007

# Telemetry batching (decision #6): the host samples ~1/s and publishes one telemetry message
# per window, or earlier once the batch is full. Limits apply to the whole message.
TELEMETRY_BATCH_WINDOW_S: Final[float] = 5.0
TELEMETRY_MAX_SAMPLES: Final[int] = 32
METRIC_NAME_PATTERN: Final[str] = r"^[a-z][a-z0-9_]{0,63}$"


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_readings(value: dict[str, MetricValue]) -> dict[str, MetricValue]:
    if not value:
        raise ValueError("a sample must contain at least one reading")
    for key, reading in value.items():
        if not isinstance(reading, MetricValue):  # type: ignore[arg-type]
            raise ValueError(f"reading {key!r} must be a scalar, got {type(reading).__name__}")
    return value


class TelemetrySample(_Payload):
    """One sensor sample. Keeps its own timestamp; the envelope timestamp is the flush time."""

    ts: AwareDatetime
    readings: dict[str, Any]

    @field_validator("readings")
    @classmethod
    def _scalar_readings(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key in value:
            if not re.fullmatch(METRIC_NAME_PATTERN, key):
                raise ValueError(f"reading name {key!r} must match {METRIC_NAME_PATTERN}")
        return _check_readings(value)


class TelemetryPayload(_Payload):
    """A batch of 1..32 samples, ordered by ``ts``."""

    samples: list[TelemetrySample] = Field(min_length=1, max_length=TELEMETRY_MAX_SAMPLES)

    @field_validator("samples")
    @classmethod
    def _ordered(cls, value: list[TelemetrySample]) -> list[TelemetrySample]:
        if any(b.ts < a.ts for a, b in itertools.pairwise(value)):
            raise ValueError("samples must be ordered by ts")
        return value


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
    DEGRADED = "degraded"  # host is online but the board is unreachable over USB
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"


class StatusPayload(_Payload):
    state: DeviceState
    uptime_s: int | None = Field(default=None, ge=0)
    detail: str | None = Field(default=None, max_length=1024)


class HeartbeatPayload(_Payload):
    uptime_s: int = Field(ge=0)


class EventSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class EventPayload(_Payload):
    """A discrete occurrence, e.g. ``board_disconnected`` or ``offline_buffer_overflow``."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    severity: EventSeverity = EventSeverity.INFO
    detail: str | None = Field(default=None, max_length=1024)
    data: dict[str, MetricValue] = Field(default_factory=dict)


class CommandPayload(_Payload):
    """Cloud -> device. Commands are named operations from an allowlist on the host runtime.

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
    MessageType.EVENT: EventPayload,
    MessageType.COMMAND: CommandPayload,
    MessageType.COMMAND_RESULT: CommandResultPayload,
}


def validate_payload(message_type: MessageType, payload: dict[str, Any]) -> BaseModel:
    return PAYLOAD_MODELS[message_type].model_validate(payload)
