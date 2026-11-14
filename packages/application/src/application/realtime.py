"""Realtime collaboration event contract (delivered via AppSync Events in AWS).

Channel layout:

* ``projects/{project_id}/sessions/{session_id}`` — session activity (presence, AI runs, ...).
* ``projects/{project_id}/devices/{device_id}`` — one device's telemetry, logs and command
  results, for everyone viewing that device.

Every event names exactly one of ``session_id`` / ``device_id``; that picks its channel.
Events are notifications; clients must refetch authoritative state from the API after a
reconnect or a missed event. Never put secrets, credentials or device commands in events.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final
from uuid import UUID, uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

MAX_EVENT_BYTES: Final[int] = 8 * 1024
REALTIME_SCHEMA_VERSION: Final[int] = 1


class RealtimeEventType(StrEnum):
    USER_JOINED = "user.joined"
    USER_LEFT = "user.left"
    DEVICE_CONNECTED = "device.connected"
    DEVICE_DISCONNECTED = "device.disconnected"
    DEVICE_STATUS_CHANGED = "device.status_changed"
    PROJECT_ACTIVITY = "project.activity"
    AI_RUN_STARTED = "ai.run.started"
    AI_RUN_DELTA = "ai.run.delta"
    AI_RUN_COMPLETED = "ai.run.completed"
    FIRMWARE_BUILD_STARTED = "firmware.build.started"
    FIRMWARE_BUILD_COMPLETED = "firmware.build.completed"
    DEVICE_TELEMETRY = "device.telemetry"
    DEVICE_LOG = "device.log"
    DEVICE_COMMAND_UPDATED = "device.command.updated"


DEVICE_EVENT_TYPES: Final[tuple[RealtimeEventType, ...]] = (
    RealtimeEventType.DEVICE_TELEMETRY,
    RealtimeEventType.DEVICE_LOG,
    RealtimeEventType.DEVICE_COMMAND_UPDATED,
)

# Keys that must never appear anywhere in an event's data.
FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {"password", "secret", "token", "private_key", "certificate", "credentials", "command"}
)


def channel_segment(resource_id: str) -> str:
    """An id as an AppSync Events channel segment, which allows only ``[A-Za-z0-9-]``.

    Our ids are ``<prefix>_<hex>`` (``prj_...``, ``dev_...``), so swapping ``_`` for ``-`` is
    reversible with ``resource_id_from_segment``.
    """
    return resource_id.replace("_", "-")


def resource_id_from_segment(segment: str) -> str:
    return segment.replace("-", "_", 1)


def session_channel(project_id: str, session_id: str) -> str:
    return f"projects/{channel_segment(project_id)}/sessions/{channel_segment(session_id)}"


def device_channel(project_id: str, device_id: str) -> str:
    return f"projects/{channel_segment(project_id)}/devices/{channel_segment(device_id)}"


class RealtimeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    schema_version: int = REALTIME_SCHEMA_VERSION
    type: RealtimeEventType
    project_id: str
    session_id: str | None = None
    device_id: str | None = None
    actor_id: str | None = None  # user id, device id, or None for system
    occurred_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_scope(self) -> RealtimeEvent:
        if (self.session_id is None) == (self.device_id is None):
            raise ValueError("an event needs exactly one of session_id or device_id")
        return self

    @property
    def channel(self) -> str:
        if self.session_id is not None:
            return session_channel(self.project_id, self.session_id)
        assert self.device_id is not None
        return device_channel(self.project_id, self.device_id)

    @field_validator("data")
    @classmethod
    def _safe_data(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_forbidden_keys(value)
        size = len(json.dumps(value, default=str).encode())
        if size > MAX_EVENT_BYTES:
            raise ValueError(f"event data is {size} bytes; limit is {MAX_EVENT_BYTES}")
        return value


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise ValueError(f"event data must not contain {key!r}")
            _reject_forbidden_keys(inner)
    elif isinstance(value, list):
        for inner in value:
            _reject_forbidden_keys(inner)
