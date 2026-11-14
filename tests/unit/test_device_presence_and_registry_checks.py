"""Ingest refuses unregistered/revoked devices, and applies IoT presence lifecycle events."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from application.services import IngestOutcome
from device_protocol import DeviceEnvelope, MessageType, RejectionReason, encode_message
from domain.devices import ConnectionStatus

NOW = datetime(2026, 11, 14, 21, 0, tzinfo=UTC)


def _telemetry(device_id: str) -> bytes:
    env = DeviceEnvelope.new(
        device_id=device_id,
        message_type=MessageType.TELEMETRY,
        payload={"samples": [{"ts": NOW.isoformat(), "readings": {"temperature_c": 40.0}}]},
        timestamp=NOW,
    )
    return encode_message(env)


def _presence(event_type: str, client_id: str = "dev-1", at: datetime = NOW, **extra) -> bytes:
    body = {
        "clientId": client_id,
        "timestamp": int(at.timestamp() * 1000),
        "eventType": event_type,
        "sessionIdentifier": "00000000-0000-0000-0000-000000000000",
        "principalIdentifier": "cert-id",
        "versionNumber": 1,
        **extra,
    }
    return json.dumps(body).encode()


def _presence_topic(event_type: str, client_id: str = "dev-1") -> str:
    return f"$aws/events/presence/{event_type}/{client_id}"


def _revoke(ingest, device_id: str = "dev-1") -> None:
    ingest.devices.save(ingest.devices.get(device_id).revoke(NOW - timedelta(minutes=1)))


def test_unregistered_device_is_rejected_and_quarantined(ingest) -> None:
    body = _telemetry("dev-unknown")
    result = ingest.service.ingest(
        topic="devices/dev-unknown/telemetry", body=body, received_at=NOW
    )
    assert result.outcome is IngestOutcome.REJECTED
    assert result.reason is RejectionReason.UNKNOWN_DEVICE
    assert ingest.raw.quarantined == [("dev-unknown", NOW, body, "unknown_device")]
    assert ingest.raw.items == []
    assert ingest.telemetry.telemetry == []


def test_revoked_device_messages_are_quarantined_and_never_recorded(ingest) -> None:
    _revoke(ingest)
    body = _telemetry("dev-1")
    result = ingest.service.ingest(topic="devices/dev-1/telemetry", body=body, received_at=NOW)
    assert result.outcome is IngestOutcome.REJECTED
    assert result.reason is RejectionReason.DEVICE_REVOKED
    assert ingest.raw.quarantined == [("dev-1", NOW, body, "device_revoked")]
    assert ingest.raw.items == []
    assert ingest.telemetry.telemetry == []
    assert ingest.devices.get("dev-1").connection_status is ConnectionStatus.OFFLINE


def test_revoked_message_is_not_claimed_for_dedupe(ingest) -> None:
    """A quarantined message must not burn its idempotency key."""
    body = _telemetry("dev-1")
    _revoke(ingest)
    ingest.service.ingest(topic="devices/dev-1/telemetry", body=body, received_at=NOW)
    assert len(ingest.raw.quarantined) == 1
    ingest.service.ingest(topic="devices/dev-1/telemetry", body=body, received_at=NOW)
    assert len(ingest.raw.quarantined) == 2


def test_connected_then_disconnected_sets_online_then_offline(ingest) -> None:
    result = ingest.service.ingest(
        topic=_presence_topic("connected"), body=_presence("connected"), received_at=NOW
    )
    assert result.outcome is IngestOutcome.PROCESSED
    device = ingest.devices.get("dev-1")
    assert device.connection_status is ConnectionStatus.ONLINE
    assert device.last_seen_at == NOW

    later = NOW + timedelta(minutes=5)
    ingest.service.ingest(
        topic=_presence_topic("disconnected"),
        body=_presence("disconnected", at=later, disconnectReason="CONNECTION_LOST"),
        received_at=later,
    )
    assert ingest.devices.get("dev-1").connection_status is ConnectionStatus.OFFLINE


def test_superseded_session_disconnect_does_not_mark_offline(ingest) -> None:
    ingest.service.ingest(
        topic=_presence_topic("connected"), body=_presence("connected"), received_at=NOW
    )
    later = NOW + timedelta(seconds=1)
    result = ingest.service.ingest(
        topic=_presence_topic("disconnected"),
        body=_presence("disconnected", at=later, disconnectReason="DUPLICATE_CLIENTID"),
        received_at=later,
    )
    assert result.outcome is IngestOutcome.IGNORED
    assert ingest.devices.get("dev-1").connection_status is ConnectionStatus.ONLINE


def test_out_of_order_presence_event_is_ignored(ingest) -> None:
    ingest.service.ingest(
        topic=_presence_topic("connected"), body=_presence("connected"), received_at=NOW
    )
    earlier = NOW - timedelta(minutes=1)
    result = ingest.service.ingest(
        topic=_presence_topic("disconnected"),
        body=_presence("disconnected", at=earlier, disconnectReason="CONNECTION_LOST"),
        received_at=NOW,
    )
    assert result.outcome is IngestOutcome.IGNORED
    assert ingest.devices.get("dev-1").connection_status is ConnectionStatus.ONLINE


@pytest.mark.parametrize(
    ("topic", "body", "reason"),
    [
        (_presence_topic("connected"), b"not json", RejectionReason.INVALID_PAYLOAD),
        (_presence_topic("connected"), _presence("exploded"), RejectionReason.INVALID_PAYLOAD),
        (_presence_topic("connected", "dev-2"), _presence("connected"), "identity"),
        (_presence_topic("disconnected"), _presence("connected"), "identity"),
        (
            _presence_topic("connected", "dev-unknown"),
            _presence("connected", "dev-unknown"),
            RejectionReason.UNKNOWN_DEVICE,
        ),
    ],
)
def test_bad_presence_events_are_quarantined(ingest, topic, body, reason) -> None:
    if reason == "identity":
        reason = RejectionReason.IDENTITY_MISMATCH
    result = ingest.service.ingest(topic=topic, body=body, received_at=NOW)
    assert result.reason is reason
    assert len(ingest.raw.quarantined) == 1
    assert ingest.devices.get("dev-1").connection_status is ConnectionStatus.UNKNOWN


def test_revoked_device_presence_is_quarantined(ingest) -> None:
    _revoke(ingest)
    result = ingest.service.ingest(
        topic=_presence_topic("connected"), body=_presence("connected"), received_at=NOW
    )
    assert result.reason is RejectionReason.DEVICE_REVOKED
    assert ingest.devices.get("dev-1").connection_status is ConnectionStatus.OFFLINE
