"""Validate and record messages that devices publish.

Pipeline for each message (at-least-once delivery, so this must be idempotent):

1. Derive the device id from the MQTT topic (authorised by the IoT policy).
2. Decode + validate against the shared protocol. Permanent failures -> ``REJECTED``.
3. Check the envelope's device id and message type match the topic.
4. Claim the idempotency key; if already claimed -> ``DUPLICATE`` (no side effects).
5. Store the raw message, write normalised records, update device last-seen/status.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from application.ports import (
    DeviceRepository,
    ProcessedMessageStore,
    RawDeviceMessageStore,
    TelemetryRepository,
)
from device_protocol import (
    DeviceEnvelope,
    MessageType,
    MessageValidationError,
    RejectionReason,
    decode_message,
    parse_topic,
)
from device_protocol.schemas import (
    DeviceState,
    LogPayload,
    StatusPayload,
    TelemetryPayload,
)
from device_protocol.topics import DEVICE_TO_CLOUD_CHANNELS, InvalidTopicError, channel_accepts
from domain.devices import ConnectionStatus


class IngestOutcome(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class IngestResult:
    outcome: IngestOutcome
    device_id: str | None = None
    message_id: str | None = None
    reason: RejectionReason | None = None
    detail: str | None = None


class DeviceMessageIngestService:
    def __init__(
        self,
        *,
        devices: DeviceRepository,
        processed: ProcessedMessageStore,
        raw_store: RawDeviceMessageStore,
        telemetry: TelemetryRepository,
    ) -> None:
        self._devices = devices
        self._processed = processed
        self._raw_store = raw_store
        self._telemetry = telemetry

    def ingest(self, *, topic: str, body: bytes, received_at: datetime) -> IngestResult:
        try:
            topic_device_id, channel = parse_topic(topic)
        except InvalidTopicError as exc:
            return _rejected(RejectionReason.WRONG_CHANNEL, str(exc))
        if channel not in DEVICE_TO_CLOUD_CHANNELS:
            return _rejected(
                RejectionReason.WRONG_CHANNEL, f"{channel.value} is cloud-to-device only"
            )

        try:
            decoded = decode_message(body)
        except MessageValidationError as exc:
            return _rejected(exc.reason, exc.detail, device_id=topic_device_id)

        envelope = decoded.envelope
        if envelope.device_id != topic_device_id:
            return _rejected(
                RejectionReason.IDENTITY_MISMATCH,
                f"payload device_id {envelope.device_id!r} != topic device {topic_device_id!r}",
                device_id=topic_device_id,
            )
        if not channel_accepts(channel, envelope.message_type):
            return _rejected(
                RejectionReason.WRONG_CHANNEL,
                f"{envelope.message_type.value} not allowed on {channel.value}",
                device_id=topic_device_id,
            )

        # TODO: also reject messages from device ids that are not registered, once IoT
        # provisioning links things to device records.
        if not self._processed.mark_processed(envelope.idempotency_key):
            return IngestResult(
                IngestOutcome.DUPLICATE,
                device_id=topic_device_id,
                message_id=str(envelope.message_id),
            )

        self._raw_store.put(
            device_id=topic_device_id,
            message_id=str(envelope.message_id),
            received_at=received_at,
            body=body,
        )
        self._record(envelope, decoded.payload)
        self._touch_device(envelope, decoded.payload)
        return IngestResult(
            IngestOutcome.PROCESSED,
            device_id=topic_device_id,
            message_id=str(envelope.message_id),
        )

    def _record(self, envelope: DeviceEnvelope, payload: object) -> None:
        message_id = str(envelope.message_id)
        if isinstance(payload, TelemetryPayload):
            self._telemetry.add_telemetry(
                device_id=envelope.device_id,
                message_id=message_id,
                at=envelope.timestamp,
                metrics=dict(payload.metrics()),
            )
        elif isinstance(payload, LogPayload):
            self._telemetry.add_log(
                device_id=envelope.device_id,
                message_id=message_id,
                at=envelope.timestamp,
                level=payload.level.value,
                message=payload.message,
            )
        # TODO: COMMAND_RESULT -> update the originating command/job record.

    def _touch_device(self, envelope: DeviceEnvelope, payload: object) -> None:
        device = self._devices.get(envelope.device_id)
        if device is None:
            return
        status = ConnectionStatus.ONLINE
        if (
            envelope.message_type is MessageType.STATUS
            and isinstance(payload, StatusPayload)
            and payload.state is DeviceState.SHUTTING_DOWN
        ):
            status = ConnectionStatus.OFFLINE
        # TODO: OFFLINE should primarily come from IoT lifecycle events
        # ($aws/events/presence/disconnected/...), not from device messages.
        self._devices.save(
            device.observed(
                envelope.timestamp, status=status, firmware_version=envelope.firmware_version
            )
        )


def _rejected(
    reason: RejectionReason, detail: str, *, device_id: str | None = None
) -> IngestResult:
    return IngestResult(IngestOutcome.REJECTED, device_id=device_id, reason=reason, detail=detail)
