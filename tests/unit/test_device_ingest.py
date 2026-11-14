from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from application.services import IngestOutcome
from device_protocol import DeviceEnvelope, MessageType, RejectionReason, encode_message
from domain.devices import ConnectionStatus, Device

NOW = datetime(2026, 11, 14, 18, 30, tzinfo=UTC)


def _body(device_id: str = "dev-1", message_type=MessageType.TELEMETRY, payload=None, **kw):
    env = DeviceEnvelope.new(
        device_id=device_id,
        message_type=message_type,
        payload=payload if payload is not None else {"temperature_c": 40.0},
        timestamp=NOW,
        **kw,
    )
    return env, encode_message(env)


def test_valid_telemetry_is_processed_and_recorded(ingest) -> None:
    env, body = _body()
    result = ingest.service.ingest(topic="devices/dev-1/telemetry", body=body, received_at=NOW)
    assert result.outcome is IngestOutcome.PROCESSED
    assert result.message_id == str(env.message_id)
    assert len(ingest.raw.items) == 1
    assert ingest.telemetry.telemetry[0]["metrics"] == {"temperature_c": 40.0}


def test_redelivered_message_is_a_duplicate_with_no_side_effects(ingest) -> None:
    _, body = _body()
    first = ingest.service.ingest(topic="devices/dev-1/telemetry", body=body, received_at=NOW)
    second = ingest.service.ingest(topic="devices/dev-1/telemetry", body=body, received_at=NOW)
    assert first.outcome is IngestOutcome.PROCESSED
    assert second.outcome is IngestOutcome.DUPLICATE
    assert len(ingest.raw.items) == 1
    assert len(ingest.telemetry.telemetry) == 1


def test_same_message_id_from_different_devices_is_not_a_duplicate(ingest) -> None:
    message_id = uuid4()
    for device_id in ("dev-1", "dev-2"):
        env = DeviceEnvelope.new(
            device_id=device_id, message_type=MessageType.TELEMETRY, payload={"t": 1}
        ).model_copy(update={"message_id": message_id})
        result = ingest.service.ingest(
            topic=f"devices/{device_id}/telemetry", body=encode_message(env), received_at=NOW
        )
        assert result.outcome is IngestOutcome.PROCESSED


def test_payload_device_id_must_match_topic_identity(ingest) -> None:
    _, body = _body(device_id="dev-2")
    result = ingest.service.ingest(topic="devices/dev-1/telemetry", body=body, received_at=NOW)
    assert result.outcome is IngestOutcome.REJECTED
    assert result.reason is RejectionReason.IDENTITY_MISMATCH
    assert ingest.raw.items == []


def test_device_cannot_publish_on_commands_channel(ingest) -> None:
    _, body = _body()
    result = ingest.service.ingest(topic="devices/dev-1/commands", body=body, received_at=NOW)
    assert result.reason is RejectionReason.WRONG_CHANNEL


def test_message_type_must_match_channel(ingest) -> None:
    _, body = _body(message_type=MessageType.LOG, payload={"level": "info", "message": "hi"})
    result = ingest.service.ingest(topic="devices/dev-1/telemetry", body=body, received_at=NOW)
    assert result.reason is RejectionReason.WRONG_CHANNEL


def test_unsupported_version_is_rejected_before_processing(ingest) -> None:
    _, body = _body()
    data = json.loads(body)
    data["schema_version"] = 99
    result = ingest.service.ingest(
        topic="devices/dev-1/telemetry", body=json.dumps(data).encode(), received_at=NOW
    )
    assert result.reason is RejectionReason.UNSUPPORTED_VERSION
    assert ingest.telemetry.telemetry == []


def test_rejected_message_does_not_consume_idempotency_key(ingest) -> None:
    env, body = _body(device_id="dev-2")
    ingest.service.ingest(topic="devices/dev-1/telemetry", body=body, received_at=NOW)
    ok = ingest.service.ingest(topic="devices/dev-2/telemetry", body=body, received_at=NOW)
    assert ok.outcome is IngestOutcome.PROCESSED
    assert ok.message_id == str(env.message_id)


def test_registered_device_status_and_firmware_are_updated(ingest) -> None:
    device = Device(project_id="p", display_name="d", hardware_model="m")
    ingest.devices.add(device)
    _, body = _body(device_id=device.id, firmware_version="1.2.3")
    ingest.service.ingest(topic=f"devices/{device.id}/telemetry", body=body, received_at=NOW)
    updated = ingest.devices.get(device.id)
    assert updated.connection_status is ConnectionStatus.ONLINE
    assert updated.firmware_version == "1.2.3"
    assert updated.last_seen_at == NOW

    _, bye = _body(
        device_id=device.id, message_type=MessageType.STATUS, payload={"state": "shutting_down"}
    )
    ingest.service.ingest(topic=f"devices/{device.id}/status", body=bye, received_at=NOW)
    assert ingest.devices.get(device.id).connection_status is ConnectionStatus.OFFLINE
