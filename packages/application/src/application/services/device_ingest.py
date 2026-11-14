"""Validate and record messages that devices publish.

Pipeline for each message (at-least-once delivery, so this must be idempotent):

1. Derive the device id from the MQTT topic (authorised by the IoT policy).
2. Decode + validate against the shared protocol. Permanent failures -> ``REJECTED`` and the
   raw body is quarantined (never silently dropped).
3. Check the envelope's device id and message type match the topic.
3b. Reject messages from unregistered (``unknown_device``) or revoked (``device_revoked``)
   devices, so they are quarantined and never touch telemetry or commands.
4. Claim the idempotency key ``(device_id, message_id)``; if already claimed -> ``DUPLICATE``.
5. Gap detection on ``sequence_number`` (persisted across host reboots, decision #14): a gap
   records a ``sequence_gap`` event but never rejects the message.
6. Store the raw message, write normalised records, apply command results, update the device.

AWS IoT lifecycle events (``$aws/events/presence/{connected|disconnected}/{client_id}``) reach
the same queue (infrastructure/stacks/iot.py) and set the device online/offline. The client id
is the thing name, which is the device id (enforced by the IoT policy).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from application.ports import (
    DeviceCommandRepository,
    DeviceRepository,
    ProcessedMessageStore,
    RawDeviceMessageStore,
    SequenceTracker,
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
    CommandResultPayload,
    DeviceState,
    EventPayload,
    LogPayload,
    StatusPayload,
    TelemetryPayload,
)
from device_protocol.topics import DEVICE_TO_CLOUD_CHANNELS, InvalidTopicError, channel_accepts
from domain.devices import CommandStatus, ConnectionStatus, Device

log = logging.getLogger(__name__)

PRESENCE_TOPIC_PREFIX = "$aws/events/presence/"
# AWS sends this for the *old* session when a device reconnects with the same client id, often
# after the new session's ``connected`` event. It does not mean the device went offline.
_SUPERSEDED_SESSION = "DUPLICATE_CLIENTID"


class PresenceEvent(BaseModel):
    """The subset of an AWS IoT presence lifecycle event that ingest uses."""

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    client_id: str = Field(alias="clientId", min_length=1, max_length=128)
    timestamp_ms: int = Field(alias="timestamp", ge=0)
    event_type: Literal["connected", "disconnected"] = Field(alias="eventType")
    disconnect_reason: str | None = Field(default=None, alias="disconnectReason")

    @property
    def at(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp_ms / 1000, tz=UTC)


class IngestOutcome(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    IGNORED = "ignored"  # valid but deliberately not applied (e.g. a superseded session)


@dataclass(frozen=True, slots=True)
class IngestResult:
    outcome: IngestOutcome
    device_id: str | None = None
    message_id: str | None = None
    reason: RejectionReason | None = None
    detail: str | None = None
    sequence_gap: int = 0


class DeviceMessageIngestService:
    def __init__(
        self,
        *,
        devices: DeviceRepository,
        processed: ProcessedMessageStore,
        raw_store: RawDeviceMessageStore,
        telemetry: TelemetryRepository,
        sequences: SequenceTracker,
        commands: DeviceCommandRepository | None = None,
    ) -> None:
        self._devices = devices
        self._processed = processed
        self._raw_store = raw_store
        self._telemetry = telemetry
        self._sequences = sequences
        self._commands = commands

    def ingest(self, *, topic: str, body: bytes, received_at: datetime) -> IngestResult:
        result = self._ingest(topic=topic, body=body, received_at=received_at)
        if result.outcome is IngestOutcome.REJECTED:
            self._raw_store.quarantine(
                device_id=result.device_id,
                received_at=received_at,
                body=body,
                reason=result.reason.value if result.reason else "unknown",
            )
        return result

    def _ingest(self, *, topic: str, body: bytes, received_at: datetime) -> IngestResult:
        if topic.startswith(PRESENCE_TOPIC_PREFIX):
            return self._ingest_presence(topic, body)
        try:
            topic_device_id, channel = parse_topic(topic)
        except InvalidTopicError as exc:
            return _rejected(RejectionReason.WRONG_CHANNEL, str(exc))
        if channel not in DEVICE_TO_CLOUD_CHANNELS:
            return _rejected(
                RejectionReason.WRONG_CHANNEL,
                f"{channel.value} is cloud-to-device only",
                device_id=topic_device_id,
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

        active = self._active_device(topic_device_id)
        if isinstance(active, IngestResult):
            return active
        # TODO (spec 04, workstream G): per-device rate limit.
        if not self._processed.mark_processed(envelope.idempotency_key):
            return IngestResult(
                IngestOutcome.DUPLICATE,
                device_id=topic_device_id,
                message_id=str(envelope.message_id),
            )

        gap = 0
        if envelope.sequence_number is not None:
            gap = self._sequences.observe(topic_device_id, envelope.sequence_number)
            if gap:
                log.warning("sequence gap of %d for %s", gap, topic_device_id)
                self._telemetry.add_event(
                    device_id=topic_device_id,
                    message_id=None,
                    at=received_at,
                    name="sequence_gap",
                    severity="warning",
                    detail=f"{gap} message(s) missing before seq {envelope.sequence_number}",
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
            sequence_gap=gap,
        )

    def _active_device(self, device_id: str) -> Device | IngestResult:
        """The registered, unrevoked device, or the rejection to return instead."""
        device = self._devices.get(device_id)
        if device is None:
            return _rejected(
                RejectionReason.UNKNOWN_DEVICE, "device is not registered", device_id=device_id
            )
        if device.is_revoked:
            return _rejected(
                RejectionReason.DEVICE_REVOKED, "device has been revoked", device_id=device_id
            )
        return device

    def _ingest_presence(self, topic: str, body: bytes) -> IngestResult:
        try:
            event = PresenceEvent.model_validate_json(body)
        except ValidationError as exc:
            return _rejected(RejectionReason.INVALID_PAYLOAD, f"presence event: {exc}")
        if topic != f"{PRESENCE_TOPIC_PREFIX}{event.event_type}/{event.client_id}":
            return _rejected(
                RejectionReason.IDENTITY_MISMATCH,
                f"presence event for {event.client_id!r} on topic {topic!r}",
                device_id=event.client_id,
            )
        device = self._active_device(event.client_id)
        if isinstance(device, IngestResult):
            return device
        if event.event_type == "disconnected" and event.disconnect_reason == _SUPERSEDED_SESSION:
            return IngestResult(IngestOutcome.IGNORED, device_id=event.client_id)

        status = (
            ConnectionStatus.ONLINE if event.event_type == "connected" else ConnectionStatus.OFFLINE
        )
        updated = device.observed(event.at, status=status)
        if updated is device:
            # Older than what we already know: delivery is not ordered.
            return IngestResult(IngestOutcome.IGNORED, device_id=event.client_id)
        self._devices.save(updated)
        return IngestResult(IngestOutcome.PROCESSED, device_id=event.client_id)

    def _record(self, envelope: DeviceEnvelope, payload: object) -> None:
        message_id = str(envelope.message_id)
        if isinstance(payload, TelemetryPayload):
            for sample in payload.samples:
                self._telemetry.add_telemetry(
                    device_id=envelope.device_id,
                    message_id=message_id,
                    at=sample.ts,
                    metrics=dict(sample.readings),
                )
        elif isinstance(payload, LogPayload):
            self._telemetry.add_log(
                device_id=envelope.device_id,
                message_id=message_id,
                at=envelope.timestamp,
                level=payload.level.value,
                message=payload.message,
            )
        elif isinstance(payload, EventPayload):
            self._telemetry.add_event(
                device_id=envelope.device_id,
                message_id=message_id,
                at=envelope.timestamp,
                name=payload.name,
                severity=payload.severity.value,
                detail=payload.detail,
            )
        elif isinstance(payload, CommandResultPayload):
            self._apply_command_result(envelope, payload)

    def _apply_command_result(
        self, envelope: DeviceEnvelope, payload: CommandResultPayload
    ) -> None:
        if self._commands is None:
            return
        command = self._commands.get(str(payload.command_id))
        if command is None or command.device_id != envelope.device_id:
            # Never let one device complete another device's command.
            log.warning("ignoring result for unknown command %s", payload.command_id)
            return
        self._commands.save(
            command.complete(
                CommandStatus(payload.status.value),
                now=envelope.timestamp,
                detail=payload.detail,
                output=dict(payload.output),
            )
        )
        # TODO (spec 06/07): broadcast the result to the project's active sessions.

    def _touch_device(self, envelope: DeviceEnvelope, payload: object) -> None:
        device = self._devices.get(envelope.device_id)
        if device is None or device.is_revoked:
            return
        status = ConnectionStatus.ONLINE
        if (
            envelope.message_type is MessageType.STATUS
            and isinstance(payload, StatusPayload)
            and payload.state is DeviceState.SHUTTING_DOWN
        ):
            status = ConnectionStatus.OFFLINE
        # IoT lifecycle events are the main source of OFFLINE (see ``_ingest_presence``); a
        # graceful shutdown status is just an earlier hint.
        self._devices.save(
            device.observed(
                envelope.timestamp, status=status, firmware_version=envelope.firmware_version
            )
        )


def _rejected(
    reason: RejectionReason, detail: str, *, device_id: str | None = None
) -> IngestResult:
    return IngestResult(IngestOutcome.REJECTED, device_id=device_id, reason=reason, detail=detail)
