from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from application.services import IngestOutcome
from device_protocol import DeviceEnvelope, MessageType, RejectionReason, encode_message
from domain.devices import CommandStatus, ConnectionStatus, Device, DeviceCommand
from domain.projects import Project

NOW = datetime(2026, 11, 14, 18, 30, tzinfo=UTC)


def _batch(*temps: float) -> dict:
    return {
        "samples": [
            {"ts": (NOW + timedelta(seconds=i)).isoformat(), "readings": {"temperature_c": t}}
            for i, t in enumerate(temps)
        ]
    }


def _body(device_id="dev-1", message_type=MessageType.TELEMETRY, payload=None, **kw):
    env = DeviceEnvelope.new(
        device_id=device_id,
        message_type=message_type,
        payload=payload if payload is not None else _batch(40.0),
        timestamp=NOW,
        **kw,
    )
    return env, encode_message(env)


def _ingest(ingest, body, topic="devices/dev-1/telemetry"):
    return ingest.service.ingest(topic=topic, body=body, received_at=NOW)


def _project(ingest, project_id: str = "p") -> str:
    """Registered devices and commands belong to a project (a foreign key in PostgreSQL)."""
    ingest.projects.add(Project(id=project_id, name="Bench", owner_user_id="u"))
    return project_id


def _register(ingest, device_id: str) -> Device:
    device = Device(id=device_id, project_id=_project(ingest), display_name="d", hardware_model="m")
    ingest.devices.add(device)
    return device


def test_batched_telemetry_records_every_sample_with_its_own_timestamp(ingest) -> None:
    env, body = _body(payload=_batch(40.0, 40.5, 41.0))
    result = _ingest(ingest, body)
    assert result.outcome is IngestOutcome.PROCESSED
    assert result.message_id == str(env.message_id)
    assert len(ingest.raw.items) == 1
    assert [r["metrics"] for r in ingest.telemetry.telemetry] == [
        {"temperature_c": 40.0},
        {"temperature_c": 40.5},
        {"temperature_c": 41.0},
    ]
    assert [r["at"] for r in ingest.telemetry.telemetry] == [
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=2),
    ]


def test_redelivered_message_is_a_duplicate_with_no_side_effects(ingest) -> None:
    _, body = _body()
    assert _ingest(ingest, body).outcome is IngestOutcome.PROCESSED
    assert _ingest(ingest, body).outcome is IngestOutcome.DUPLICATE
    assert len(ingest.raw.items) == 1
    assert len(ingest.telemetry.telemetry) == 1


def test_same_message_id_from_different_devices_is_not_a_duplicate(ingest) -> None:
    message_id = uuid4()
    for device_id in ("dev-1", "dev-2"):
        env, _ = _body(device_id=device_id)
        env = env.model_copy(update={"message_id": message_id})
        result = _ingest(ingest, encode_message(env), topic=f"devices/{device_id}/telemetry")
        assert result.outcome is IngestOutcome.PROCESSED


def test_payload_device_id_must_match_topic_identity(ingest) -> None:
    _, body = _body(device_id="dev-2")
    result = _ingest(ingest, body)
    assert result.reason is RejectionReason.IDENTITY_MISMATCH
    assert ingest.raw.items == []


def test_rejected_messages_are_quarantined_not_dropped(ingest) -> None:
    _, body = _body(device_id="dev-2")
    _ingest(ingest, body)
    _ingest(ingest, b"{not json")
    reasons = [q[3] for q in ingest.raw.quarantined]
    assert reasons == ["identity_mismatch", "malformed_json"]
    assert ingest.raw.quarantined[0][2] == body


def test_device_cannot_publish_on_commands_channel(ingest) -> None:
    _, body = _body()
    assert _ingest(ingest, body, "devices/dev-1/commands").reason is RejectionReason.WRONG_CHANNEL


def test_message_type_must_match_channel(ingest) -> None:
    _, body = _body(message_type=MessageType.LOG, payload={"level": "info", "message": "hi"})
    assert _ingest(ingest, body).reason is RejectionReason.WRONG_CHANNEL


def test_unsupported_version_is_rejected_before_processing(ingest) -> None:
    _, body = _body()
    data = json.loads(body)
    data["schema_version"] = 99
    result = _ingest(ingest, json.dumps(data).encode())
    assert result.reason is RejectionReason.UNSUPPORTED_VERSION
    assert ingest.telemetry.telemetry == []


def test_rejected_message_does_not_consume_idempotency_key(ingest) -> None:
    env, body = _body(device_id="dev-2")
    _ingest(ingest, body)
    ok = _ingest(ingest, body, "devices/dev-2/telemetry")
    assert ok.outcome is IngestOutcome.PROCESSED
    assert ok.message_id == str(env.message_id)


def test_sequence_gap_is_recorded_but_message_still_processed(ingest) -> None:
    for seq in (10, 11, 14):
        _, body = _body(sequence_number=seq)
        result = _ingest(ingest, body)
        assert result.outcome is IngestOutcome.PROCESSED
    assert result.sequence_gap == 2
    [event] = ingest.telemetry.events
    assert event["name"] == "sequence_gap"
    assert "2 message(s) missing" in event["detail"]


def test_out_of_order_delivery_is_not_a_gap(ingest) -> None:
    for seq in (5, 7, 6):
        _, body = _body(sequence_number=seq)
        _ingest(ingest, body)
    assert len(ingest.telemetry.events) == 1  # only 5 -> 7


def test_device_events_are_recorded(ingest) -> None:
    _, body = _body(
        message_type=MessageType.EVENT,
        payload={"name": "board_disconnected", "severity": "warning"},
    )
    _ingest(ingest, body, "devices/dev-1/events")
    assert ingest.telemetry.events[0]["name"] == "board_disconnected"


def test_registered_device_status_and_firmware_are_updated(ingest) -> None:
    device = Device(project_id=_project(ingest), display_name="d", hardware_model="freewili-1-og")
    ingest.devices.add(device)
    _, body = _body(device_id=device.id, firmware_version="1.2.3")
    _ingest(ingest, body, f"devices/{device.id}/telemetry")
    updated = ingest.devices.get(device.id)
    assert updated.connection_status is ConnectionStatus.ONLINE
    assert updated.firmware_version == "1.2.3"
    assert updated.last_seen_at == NOW

    _, bye = _body(
        device_id=device.id, message_type=MessageType.STATUS, payload={"state": "shutting_down"}
    )
    _ingest(ingest, bye, f"devices/{device.id}/status")
    assert ingest.devices.get(device.id).connection_status is ConnectionStatus.OFFLINE


def _result_body(device_id: str, command_id: str, status: str = "succeeded") -> bytes:
    _, body = _body(
        device_id=device_id,
        message_type=MessageType.COMMAND_RESULT,
        payload={"command_id": command_id, "status": status, "output": {"pong": True}},
    )
    return body


def test_command_result_completes_the_command(ingest) -> None:
    _register(ingest, "dev-1")
    command = DeviceCommand(project_id="p", device_id="dev-1", name="ping", requested_by="u")
    ingest.commands.add(command.mark_sent(NOW))
    _ingest(ingest, _result_body("dev-1", command.id), "devices/dev-1/responses")
    done = ingest.commands.get(command.id)
    assert done.status is CommandStatus.SUCCEEDED
    assert done.output == {"pong": True}


def test_a_device_cannot_complete_another_devices_command(ingest) -> None:
    _register(ingest, "dev-1")
    command = DeviceCommand(project_id="p", device_id="dev-1", name="ping", requested_by="u")
    ingest.commands.add(command.mark_sent(NOW))
    _ingest(ingest, _result_body("dev-2", command.id), "devices/dev-2/responses")
    assert ingest.commands.get(command.id).status is CommandStatus.SENT


def test_registered_device_gets_live_telemetry_log_and_command_events(ingest) -> None:
    device = Device(
        project_id=_project(ingest, "prj_1"), display_name="d", hardware_model="freewili-1-og"
    )
    ingest.devices.add(device)
    topic = f"devices/{device.id}"
    _, body = _body(device_id=device.id, payload=_batch(40.0, 41.0))
    _ingest(ingest, body, f"{topic}/telemetry")
    _, log_body = _body(
        device_id=device.id,
        message_type=MessageType.LOG,
        payload={"level": "info", "message": "hi"},
    )
    _ingest(ingest, log_body, f"{topic}/logs")
    command = DeviceCommand(project_id="prj_1", device_id=device.id, name="ping", requested_by="u")
    ingest.commands.add(command.mark_sent(NOW))
    _ingest(ingest, _result_body(device.id, command.id), f"{topic}/responses")

    events = ingest.realtime.events
    assert [e.type.value for e in events] == [
        "device.telemetry",
        "device.log",
        "device.command.updated",
    ]
    assert {e.channel for e in events} == {f"projects/prj-1/devices/{device.id.replace('_', '-')}"}
    assert [s["readings"] for s in events[0].data["samples"]] == [
        {"temperature_c": 40.0},
        {"temperature_c": 41.0},
    ]
    assert events[1].data == {
        "at": NOW.isoformat(),
        "kind": "log",
        "level": "info",
        "message": "hi",
    }
    assert events[2].data["command_id"] == command.id
    assert events[2].data["status"] == "succeeded"
    assert events[2].data["output"] == {"pong": True}


def test_unregistered_devices_and_repeated_results_publish_nothing(ingest) -> None:
    _, body = _body(device_id="dev-9")
    _ingest(ingest, body, "devices/dev-9/telemetry")  # never registered: nobody to tell
    _register(ingest, "dev-1")
    command = DeviceCommand(project_id="p", device_id="dev-1", name="ping", requested_by="u")
    ingest.commands.add(command.mark_sent(NOW))
    _ingest(ingest, _result_body("dev-1", command.id), "devices/dev-1/responses")
    _ingest(ingest, _result_body("dev-1", command.id, "failed"), "devices/dev-1/responses")
    # Only the first result changes the command, and only it is announced.
    assert [e.type.value for e in ingest.realtime.events] == ["device.command.updated"]
    assert ingest.commands.get(command.id).status is CommandStatus.SUCCEEDED


def test_an_event_that_breaks_the_contract_is_dropped_not_raised(ingest) -> None:
    _register(ingest, "dev-1")
    command = DeviceCommand(project_id="p", device_id="dev-1", name="ping", requested_by="u")
    ingest.commands.add(command.mark_sent(NOW))
    _, body = _body(
        device_id="dev-1",
        message_type=MessageType.COMMAND_RESULT,
        payload={"command_id": command.id, "status": "succeeded", "output": {"token": "x"}},
    )
    result = _ingest(ingest, body, "devices/dev-1/responses")
    assert result.outcome is IngestOutcome.PROCESSED
    assert ingest.commands.get(command.id).status is CommandStatus.SUCCEEDED
    assert ingest.realtime.events == []


def test_recent_reads_return_the_newest_records_oldest_first(ingest) -> None:
    _, body = _body(payload=_batch(1.0, 2.0, 3.0))
    _ingest(ingest, body)
    _, ev = _body(
        message_type=MessageType.EVENT,
        payload={"name": "board_disconnected", "severity": "warning", "detail": "usb"},
    )
    _ingest(ingest, ev, "devices/dev-1/events")
    recent = ingest.telemetry.recent_telemetry("dev-1", limit=2)
    assert [s.readings for s in recent] == [{"temperature_c": 2.0}, {"temperature_c": 3.0}]
    [entry] = ingest.telemetry.recent_logs("dev-1", limit=10)
    assert (entry.kind, entry.level, entry.message) == (
        "event",
        "warning",
        "board_disconnected: usb",
    )
    assert ingest.telemetry.recent_telemetry("other", limit=5) == []
