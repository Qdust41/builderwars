"""Realtime collaboration event contract (delivered via AppSync Events in AWS).

Channel layout: ``projects/{project_id}/sessions/{session_id}``.
Events are notifications; clients must refetch authoritative state from the API after a
reconnect or a missed event. Never put secrets, credentials or device commands in events.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

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


# Keys that must never appear anywhere in an event's data.
FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {"password", "secret", "token", "private_key", "certificate", "credentials", "command"}
)


def session_channel(project_id: str, session_id: str) -> str:
    return f"projects/{project_id}/sessions/{session_id}"


class RealtimeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    schema_version: int = REALTIME_SCHEMA_VERSION
    type: RealtimeEventType
    project_id: str
    session_id: str
    actor_id: str | None = None  # user id, device id, or None for system
    occurred_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)

    @property
    def channel(self) -> str:
        return session_channel(self.project_id, self.session_id)

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
