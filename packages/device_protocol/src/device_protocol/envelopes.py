"""The versioned envelope that wraps every device <-> cloud message."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Final
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from device_protocol.versioning import CURRENT_SCHEMA_VERSION, ensure_supported

# Provisional limits. AWS IoT Core caps MQTT payloads at 128 KiB; we stay well below that so
# telemetry stays cheap and a misbehaving board cannot flood consumers. Revisit once message
# rates and payload sizes are known (docs/open-decisions.md #6).
MAX_MESSAGE_BYTES: Final[int] = 32 * 1024
MAX_PAYLOAD_BYTES: Final[int] = 16 * 1024

DeviceId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
VersionLabel = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class MessageType(StrEnum):
    TELEMETRY = "telemetry"
    LOG = "log"
    STATUS = "status"
    COMMAND = "command"
    COMMAND_RESULT = "command_result"
    HEARTBEAT = "heartbeat"


class DeviceEnvelope(BaseModel):
    """Envelope shared by board and cloud.

    ``device_id`` here is informational. It is NOT proof of identity: consumers must compare it
    with the device id derived from the authorised MQTT topic and reject mismatches.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: UUID
    schema_version: int
    device_id: DeviceId
    timestamp: AwareDatetime
    message_type: MessageType
    sequence_number: int | None = Field(default=None, ge=0)
    firmware_version: VersionLabel | None = None
    hardware_model: VersionLabel | None = None
    payload: dict[str, Any]

    @field_validator("schema_version")
    @classmethod
    def _supported_version(cls, value: int) -> int:
        return ensure_supported(value)

    @field_validator("payload")
    @classmethod
    def _payload_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        size = len(json.dumps(value, separators=(",", ":")).encode())
        if size > MAX_PAYLOAD_BYTES:
            raise ValueError(f"payload is {size} bytes; limit is {MAX_PAYLOAD_BYTES}")
        return value

    @property
    def idempotency_key(self) -> str:
        """Key used by consumers to drop redeliveries (delivery is at-least-once)."""
        return f"{self.device_id}:{self.message_id}"

    @classmethod
    def new(
        cls,
        *,
        device_id: str,
        message_type: MessageType,
        payload: dict[str, Any],
        sequence_number: int | None = None,
        firmware_version: str | None = None,
        hardware_model: str | None = None,
        timestamp: datetime | None = None,
    ) -> DeviceEnvelope:
        return cls(
            message_id=uuid4(),
            schema_version=CURRENT_SCHEMA_VERSION,
            device_id=device_id,
            timestamp=timestamp or datetime.now(UTC),
            message_type=message_type,
            sequence_number=sequence_number,
            firmware_version=firmware_version,
            hardware_model=hardware_model,
            payload=payload,
        )
