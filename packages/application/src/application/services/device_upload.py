"""Device messages uploaded by a signed-in user (the ``builderwars`` CLI), not by the board.

Boards have no AWS IoT certificates yet. Instead the person running the board signs in to the
CLI with their own account, and the CLI posts the board's protocol messages (telemetry, logs,
status, events) to ``POST /devices/{device_id}/messages``. Identity therefore comes from the
user's token plus project membership, not from an MQTT topic the broker authorised:

* the caller needs ``device:upload`` on the device's project (members and up);
* every message's topic and envelope must name the device in the URL, so one upload can never
  write into another device, even one the same user can reach.

After that a message goes through exactly the same pipeline as the MQTT path
(``DeviceMessageIngestService``): validation, idempotency on ``(device_id, message_id)`` so a
re-upload is harmless, sequence gaps, storage. Realtime events for the dashboard are collected
while the batch is ingested and published afterwards in as few calls as the publisher allows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from application.ports import (
    DeviceCommandRepository,
    DeviceRepository,
    ProcessedMessageStore,
    RawDeviceMessageStore,
    RealtimePublisher,
    SequenceTracker,
    TelemetryRepository,
)
from application.realtime import RealtimeEvent
from application.services.authorization import Authorizer
from application.services.device_events import DeviceEventPublisher
from application.services.device_ingest import (
    DeviceMessageIngestService,
    IngestOutcome,
    IngestResult,
)
from device_protocol import RejectionReason, parse_topic
from device_protocol.topics import InvalidTopicError
from domain.common import NotFoundError
from domain.projects import Permission

log = logging.getLogger(__name__)

MAX_MESSAGES_PER_UPLOAD = 200


@dataclass(frozen=True, slots=True)
class UploadedMessage:
    topic: str
    body: bytes


class _CollectingPublisher:
    def __init__(self) -> None:
        self.events: list[RealtimeEvent] = []

    def publish(self, event: RealtimeEvent) -> None:
        self.events.append(event)


def publish_all(publisher: RealtimePublisher, events: list[RealtimeEvent]) -> None:
    """Publish ``events`` in order; uses ``publish_batch`` when the adapter has one.

    Realtime events are hints, so a failure is logged and never fails the upload.
    """
    if not events:
        return
    try:
        batch = getattr(publisher, "publish_batch", None)
        if callable(batch):
            batch(events)
        else:
            for event in events:
                publisher.publish(event)
    except Exception:
        log.exception("failed to publish %d realtime event(s) for an upload", len(events))


class DeviceUploadService:
    def __init__(
        self,
        *,
        devices: DeviceRepository,
        authorizer: Authorizer,
        processed: ProcessedMessageStore,
        raw_store: RawDeviceMessageStore,
        telemetry: TelemetryRepository,
        sequences: SequenceTracker,
        commands: DeviceCommandRepository,
        realtime: RealtimePublisher,
    ) -> None:
        self._devices = devices
        self._authorizer = authorizer
        self._processed = processed
        self._raw_store = raw_store
        self._telemetry = telemetry
        self._sequences = sequences
        self._commands = commands
        self._realtime = realtime

    def upload(
        self,
        *,
        user_id: str,
        device_id: str,
        messages: list[UploadedMessage],
        received_at: datetime,
    ) -> list[IngestResult]:
        device = self._devices.get(device_id)
        if device is None:
            raise NotFoundError("device", device_id)
        try:
            self._authorizer.require(user_id, device.project_id, Permission.UPLOAD_DEVICE_DATA)
        except NotFoundError:
            raise NotFoundError("device", device_id) from None
        if len(messages) > MAX_MESSAGES_PER_UPLOAD:
            raise ValueError(f"at most {MAX_MESSAGES_PER_UPLOAD} messages per upload")

        collector = _CollectingPublisher()
        ingest = DeviceMessageIngestService(
            devices=self._devices,
            processed=self._processed,
            raw_store=self._raw_store,
            telemetry=self._telemetry,
            sequences=self._sequences,
            commands=self._commands,
            events=DeviceEventPublisher(collector),
        )
        results = [self._one(ingest, device_id, m, received_at) for m in messages]
        publish_all(self._realtime, collector.events)
        return results

    def _one(
        self,
        ingest: DeviceMessageIngestService,
        device_id: str,
        message: UploadedMessage,
        received_at: datetime,
    ) -> IngestResult:
        # The topic stands in for the MQTT topic the broker would have authorised, so it must
        # name the device the caller is authorised for. The ingest pipeline then checks the
        # envelope's device id against the topic, as it does for MQTT.
        try:
            topic_device_id, _ = parse_topic(message.topic)
        except InvalidTopicError as exc:
            return IngestResult(
                IngestOutcome.REJECTED, reason=RejectionReason.WRONG_CHANNEL, detail=str(exc)
            )
        if topic_device_id != device_id:
            return IngestResult(
                IngestOutcome.REJECTED,
                device_id=device_id,
                reason=RejectionReason.IDENTITY_MISMATCH,
                detail=f"topic device {topic_device_id!r} != upload device {device_id!r}",
            )
        return ingest.ingest(topic=message.topic, body=message.body, received_at=received_at)
