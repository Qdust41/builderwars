from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from board_runtime.commands import CommandDispatcher
from board_runtime.config import ConfigError, DeviceConfig, TransportKind
from board_runtime.connectivity import BackoffPolicy, BoundedMemoryBuffer, RecordingTransport
from board_runtime.hardware import SimulatedSensors
from board_runtime.main import BoardRuntime
from device_protocol import DeviceEnvelope, MessageType, decode_message, encode_message
from device_protocol.schemas import CommandPayload, CommandResultStatus


def _config() -> DeviceConfig:
    return DeviceConfig(
        device_id="dev-1",
        hardware_model="m",
        firmware_version="1.0",
        transport=TransportKind.STDOUT,
    )


def test_buffer_drops_oldest_when_full() -> None:
    buf = BoundedMemoryBuffer(2)
    for i in range(3):
        buf.append("t", str(i).encode())
    assert buf.dropped == 1
    assert [buf.pop(), buf.pop(), buf.pop()] == [("t", b"1"), ("t", b"2"), None]


def test_backoff_grows_and_is_capped() -> None:
    policy = BackoffPolicy(base_s=1, max_s=10, multiplier=2)
    assert [policy.ceiling(a) for a in range(5)] == [1, 2, 4, 8, 10]
    rng = random.Random(0)
    assert all(0 <= policy.delay(a, rng) <= policy.ceiling(a) for a in range(10))


def test_mqtt_config_requires_endpoint_and_cert_paths() -> None:
    with pytest.raises(ConfigError, match="IOT_ENDPOINT"):
        DeviceConfig.from_env({"DEVICE_ID": "d", "DEVICE_TRANSPORT": "mqtt"})
    with pytest.raises(ConfigError, match="DEVICE_ID"):
        DeviceConfig.from_env({})


def test_runtime_buffers_during_outage_and_flushes_in_order() -> None:
    transport = RecordingTransport()
    runtime = BoardRuntime(_config(), transport, SimulatedSensors(seed=1))
    runtime.start()
    transport.fail_publishes = True
    runtime.tick()
    runtime.tick()
    assert len(runtime.buffer) == 2
    transport.fail_publishes = False
    runtime.heartbeat()
    sequences = [json.loads(body)["sequence_number"] for _, body in transport.published]
    assert sequences == [0, 1, 2, 3]
    assert len(runtime.buffer) == 0


def test_every_runtime_message_is_valid_protocol() -> None:
    transport = RecordingTransport()
    runtime = BoardRuntime(_config(), transport, SimulatedSensors(seed=1))
    runtime.start()
    runtime.tick()
    runtime.heartbeat()
    runtime.stop()
    types = [decode_message(body).envelope.message_type for _, body in transport.published]
    assert types == [
        MessageType.STATUS,
        MessageType.TELEMETRY,
        MessageType.HEARTBEAT,
        MessageType.STATUS,
    ]


def _command(name: str, *, expires_in: timedelta | None = None, device_id: str = "dev-1") -> bytes:
    payload = {"command_id": str(uuid4()), "name": name, "args": {}}
    if expires_in is not None:
        payload["expires_at"] = (datetime.now(UTC) + expires_in).isoformat()
    env = DeviceEnvelope.new(device_id=device_id, message_type=MessageType.COMMAND, payload=payload)
    return encode_message(env)


def _results(transport: RecordingTransport) -> list[dict]:
    return [
        json.loads(body)["payload"]
        for topic, body in transport.published
        if topic.endswith("/responses")
    ]


def test_runtime_answers_allowed_command() -> None:
    transport = RecordingTransport()
    runtime = BoardRuntime(_config(), transport, SimulatedSensors())
    runtime.start()
    transport.deliver("devices/dev-1/commands", _command("ping"))
    [result] = _results(transport)
    assert result["status"] == "succeeded"
    assert result["output"] == {"pong": True}


@pytest.mark.parametrize(
    ("name", "expires_in", "detail"),
    [
        ("reboot_into_shell", None, "not allowed"),
        ("ping", timedelta(seconds=-1), "expired"),
    ],
)
def test_runtime_rejects_unknown_or_expired_commands(name, expires_in, detail) -> None:
    transport = RecordingTransport()
    runtime = BoardRuntime(_config(), transport, SimulatedSensors())
    runtime.start()
    transport.deliver("devices/dev-1/commands", _command(name, expires_in=expires_in))
    [result] = _results(transport)
    assert result["status"] == "rejected"
    assert detail in result["detail"]


def test_runtime_ignores_commands_for_other_devices() -> None:
    transport = RecordingTransport()
    runtime = BoardRuntime(_config(), transport, SimulatedSensors())
    runtime.start()
    transport.deliver("devices/dev-1/commands", _command("ping", device_id="dev-2"))
    assert _results(transport) == []


def test_dispatcher_reports_handler_failures() -> None:
    dispatcher = CommandDispatcher()

    def broken(_: dict) -> dict:
        raise RuntimeError("sensor bus fault")

    dispatcher.register("read_bus", broken)
    cmd = CommandPayload(command_id=uuid4(), name="read_bus")
    assert dispatcher.dispatch(cmd).status is CommandResultStatus.FAILED
    with pytest.raises(ValueError, match="already registered"):
        dispatcher.register("read_bus", broken)
