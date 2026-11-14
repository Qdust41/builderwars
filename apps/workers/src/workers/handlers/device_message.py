"""Handle device messages forwarded from AWS IoT Core.

In AWS, an IoT topic rule forwards device-to-cloud topics to an SQS queue with:

    SELECT topic() AS topic, timestamp() AS received_at_ms, encode(*, 'base64') AS body_b64
    FROM 'devices/+/+'

(see infrastructure/stacks/iot.py). The topic is captured by the broker, so it reflects the
authenticated device identity; the body is passed through untouched.
"""

from __future__ import annotations

import base64
import binascii
import logging
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from application.services import DeviceMessageIngestService, IngestOutcome, IngestResult

log = logging.getLogger(__name__)


class IncomingDeviceMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    topic: str = Field(max_length=256)
    received_at_ms: int = Field(ge=0)
    body_b64: str

    def body(self) -> bytes:
        try:
            return base64.b64decode(self.body_b64, validate=True)
        except binascii.Error as exc:
            raise ValueError("body_b64 is not valid base64") from exc

    @property
    def received_at(self) -> datetime:
        return datetime.fromtimestamp(self.received_at_ms / 1000, tz=UTC)

    @classmethod
    def from_raw(cls, topic: str, body: bytes, received_at: datetime) -> IncomingDeviceMessage:
        return cls(
            topic=topic,
            received_at_ms=int(received_at.timestamp() * 1000),
            body_b64=base64.b64encode(body).decode(),
        )


class DeviceMessageHandler:
    def __init__(self, ingest: DeviceMessageIngestService) -> None:
        self._ingest = ingest

    def handle(self, message: IncomingDeviceMessage) -> IngestResult:
        result = self._ingest.ingest(
            topic=message.topic, body=message.body(), received_at=message.received_at
        )
        if result.outcome is IngestOutcome.REJECTED:
            # Permanent failure: retrying cannot help, so we log and acknowledge it rather than
            # letting it bounce to the DLQ. TODO: write rejects to a quarantine store/metric.
            log.warning(
                "rejected device message",
                extra={
                    "device_id": result.device_id,
                    "reason": result.reason.value if result.reason else None,
                },
            )
        return result
