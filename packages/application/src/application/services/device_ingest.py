"""Validate and record messages that devices publish.

Pipeline for each message (at-least-once delivery, so this must be idempotent):

1. Derive the device id from the MQTT topic (authorised by the IoT policy).
2. Decode + validate against the shared protocol. Permanent failures -> ``REJECTED`` and the
   raw body is quarantined (never silently dropped).
3. Check the envelope's device id and message type match the topic.
4. Claim the idempotency key ``(device_id, message_id)``; if already claimed -> ``DUPLICATE``.
5. Gap detection on ``sequence_number`` (persisted across host reboots, decision #14): a gap
   records a ``sequence_gap`` event but never rejects the message.
6. Store the raw message, write normalised records, apply command results, update the device.
7. Notify viewers of the device (realtime, best effort) — only for registered devices.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from application.ports import (
    DeviceCommandRepository,
    DeviceRepository,
    ProcessedMessageStore,
    RawDeviceMessageStore,
    SequenceTracker,
    TelemetryRepository,
)
from application.services.device_events import DeviceEventPublisher
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
from domain.devices import CommandStatus, ConnectionStatus

log = logging.getLogger(__name__)


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
        events: DeviceEventPublisher | None = None,
    ) -> None:
        self._devices = devices
        self._processed = processed
        self._raw_store = raw_store
        self._telemetry = telemetry
        self._sequences = sequences
        self._commands = commands
        self._events = events

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

        # TODO (spec 03/04): reject unregistered/revoked device ids; per-device rate limit.
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
        self._notify(envelope, decoded.payload)
        return IngestResult(
            IngestOutcome.PROCESSED,
            device_id=topic_device_id,
            message_id=str(envelope.message_id),
            sequence_gap=gap,
        )

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
        if not command.status.is_pending:
            return  # already completed (or timed out); a redelivered result changes nothing
        completed = command.complete(
            CommandStatus(payload.status.value),
            now=envelope.timestamp,
            detail=payload.detail,
            output=dict(payload.output),
        )
        self._commands.save(completed)
        if self._events is not None:
            self._events.command_updated(completed)
        # TODO (spec 06/07): also broadcast the result to the project's active sessions.

    def _notify(self, envelope: DeviceEnvelope, payload: object) -> None:
        if self._events is None:
            return
        device = self._devices.get(envelope.device_id)
        if device is None:
            return
        project_id, device_id = device.project_id, device.id
        if isinstance(payload, TelemetryPayload):
            self._events.telemetry(
                project_id=project_id,
                device_id=device_id,
                samples=[(s.ts, dict(s.readings)) for s in payload.samples],
            )
        elif isinstance(payload, LogPayload):
            self._events.log_entry(
                project_id=project_id,
                device_id=device_id,
                at=envelope.timestamp,
                kind="log",
                level=payload.level.value,
                message=payload.message,
            )
        elif isinstance(payload, EventPayload):
            detail = f": {payload.detail}" if payload.detail else ""
            self._events.log_entry(
                project_id=project_id,
                device_id=device_id,
                at=envelope.timestamp,
                kind="event",
                level=payload.severity.value,
                message=f"{payload.name}{detail}",
            )

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
        updated = device.observed(
            envelope.timestamp, status=status, firmware_version=envelope.firmware_version
        )
        self._devices.save(updated)
        # Tell viewers when it comes online or goes away. "Online" also counts as a change
        # when the device had gone silent long enough to read as offline.
        before = device.status_at(envelope.timestamp)
        if self._events is not None and updated.connection_status is not before:
            self._events.status_changed(
                project_id=device.project_id,
                device_id=device.id,
                status=updated.connection_status.value,
                at=updated.last_seen_at,
            )


def _rejected(
    reason: RejectionReason, detail: str, *, device_id: str | None = None
) -> IngestResult:
    return IngestResult(IngestOutcome.REJECTED, device_id=device_id, reason=reason, detail=detail)
