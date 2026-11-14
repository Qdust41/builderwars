from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from board_runtime.batching import TelemetryBatcher
from board_runtime.commands import CommandDispatcher
from board_runtime.config import ConfigError, DeviceConfig, TransportKind
from board_runtime.connectivity import BackoffPolicy, BoundedMemoryBuffer, RecordingTransport
from board_runtime.firmware import ChecksumMismatchError, sha256_of, verify_sha256
from board_runtime.hardware import BoardUnavailableError, SimulatedSensors
from board_runtime.main import BoardRuntime
from board_runtime.sequence import FileSequenceStore
from device_protocol import DeviceEnvelope, MessageType, decode_message, encode_message
from device_protocol.compat import UTC
from device_protocol.schemas import CommandPayload, CommandResultStatus, TelemetryPayload


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _config(**kw) -> DeviceConfig:
    defaults = {
        "device_id": "dev-1",
        "hardware_model": "freewili-1-og",
        "firmware_version": "1.0",
        "transport": TransportKind.STDOUT,
    }
    return DeviceConfig(**{**defaults, **kw})


def _types(transport: RecordingTransport) -> list[MessageType]:
    return [decode_message(body).envelope.message_type for _, body in transport.published]


def _runtime(transport: RecordingTransport, sensors=None, **kw) -> tuple[BoardRuntime, FakeClock]:
    clock = FakeClock()
    runtime = BoardRuntime(
        _config(**kw), transport, sensors or SimulatedSensors(seed=1), clock=clock
    )
    return runtime, clock


# -- buffering / backoff / config ----------------------------------------------------------


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


def test_config_validation() -> None:
    with pytest.raises(ConfigError, match="IOT_ENDPOINT"):
        DeviceConfig.from_env({"DEVICE_ID": "d", "DEVICE_TRANSPORT": "mqtt"})
    with pytest.raises(ConfigError, match="DEVICE_ID"):
        DeviceConfig.from_env({})
    with pytest.raises(ConfigError, match="batch_max_samples"):
        _config(batch_max_samples=33).validate()
    cfg = DeviceConfig.from_env({"DEVICE_ID": "d", "BUILDERWARS_STATE_DIR": "/tmp/x"})
    assert cfg.hardware_model == "freewili-1-og"
    assert cfg.state_dir == Path("/tmp/x")


# -- telemetry batching (decision #6) ------------------------------------------------------


def test_batcher_flushes_at_sample_cap() -> None:
    batcher = TelemetryBatcher(window_s=5, max_samples=3)
    at = datetime(2026, 11, 14, tzinfo=UTC)
    assert batcher.add({"t": 1}, at=at, now=0) is None
    assert batcher.add({"t": 2}, at=at, now=1) is None
    batch = batcher.add({"t": 3}, at=at, now=2)
    assert batch is not None
    assert len(TelemetryPayload.model_validate(batch).samples) == 3
    assert len(batcher) == 0


def test_runtime_publishes_one_batch_per_window() -> None:
    transport = RecordingTransport()
    runtime, clock = _runtime(transport)
    runtime.start()
    for second in range(12):  # samples at t=0..11 s
        clock.now = float(second)
        runtime.sample()
    batches = [
        TelemetryPayload.model_validate(json.loads(body)["payload"])
        for topic, body in transport.published
        if topic.endswith("/telemetry")
    ]
    assert [len(b.samples) for b in batches] == [6, 6]  # flushed at t=5 and t=11
    assert all(len(b.samples) <= 32 for b in batches)


def test_runtime_flushes_partial_batch_on_stop() -> None:
    transport = RecordingTransport()
    runtime, _ = _runtime(transport)
    runtime.start()
    runtime.sample()
    runtime.stop()
    assert _types(transport) == [MessageType.STATUS, MessageType.TELEMETRY, MessageType.STATUS]


def test_runtime_buffers_during_outage_and_replays_in_order() -> None:
    transport = RecordingTransport()
    runtime, _ = _runtime(transport, batch_max_samples=1)
    runtime.start()
    transport.fail_publishes = True
    runtime.sample()
    runtime.sample()
    assert len(runtime.buffer) == 2
    transport.fail_publishes = False
    runtime.heartbeat()
    sequences = [json.loads(body)["sequence_number"] for _, body in transport.published]
    assert sequences == [0, 1, 2, 3]
    assert len(runtime.buffer) == 0


class FlakyBoard:
    def __init__(self) -> None:
        self.available = True

    def read(self):
        if not self.available:
            raise BoardUnavailableError("USB unplugged")
        return {"io_0": 1}


def test_board_unplug_reports_degraded_then_recovers() -> None:
    transport = RecordingTransport()
    board = FlakyBoard()
    runtime, _ = _runtime(transport, sensors=board)
    runtime.start()
    board.available = False
    runtime.sample()
    runtime.sample()  # stays degraded, no duplicate notifications
    board.available = True
    runtime.sample()
    payloads = [json.loads(body)["payload"] for _, body in transport.published]
    assert [p.get("name") or p.get("state") for p in payloads] == [
        "online",
        "board_disconnected",
        "degraded",
        "board_reconnected",
        "online",
    ]


# -- sequence persistence (decision #14) ---------------------------------------------------


def test_sequence_numbers_survive_restart(tmp_path: Path) -> None:
    store = FileSequenceStore(tmp_path, "dev-1")
    assert [store.next(), store.next()] == [0, 1]
    restarted = FileSequenceStore(tmp_path, "dev-1")
    assert restarted.next() == 2
    assert (tmp_path / "seq" / "dev-1").read_text() == "3"
    assert FileSequenceStore(tmp_path, "dev-2").next() == 0


def test_corrupt_sequence_file_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "seq").mkdir()
    (tmp_path / "seq" / "dev-1").write_text("garbage")
    with pytest.raises(RuntimeError, match="corrupt"):
        FileSequenceStore(tmp_path, "dev-1")


# -- commands ------------------------------------------------------------------------------


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
    runtime, _ = _runtime(transport)
    runtime.start()
    transport.deliver("devices/dev-1/commands", _command("ping"))
    [result] = _results(transport)
    assert result["status"] == "succeeded"
    assert result["output"] == {"pong": True}


@pytest.mark.parametrize(
    ("name", "expires_in", "detail"),
    [("reboot_into_shell", None, "not allowed"), ("ping", timedelta(seconds=-1), "expired")],
)
def test_runtime_rejects_unknown_or_expired_commands(name, expires_in, detail) -> None:
    transport = RecordingTransport()
    runtime, _ = _runtime(transport)
    runtime.start()
    transport.deliver("devices/dev-1/commands", _command(name, expires_in=expires_in))
    [result] = _results(transport)
    assert result["status"] == "rejected"
    assert detail in result["detail"]


def test_runtime_ignores_commands_for_other_devices() -> None:
    transport = RecordingTransport()
    runtime, _ = _runtime(transport)
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


# -- firmware ------------------------------------------------------------------------------


def test_uf2_checksum_is_verified_before_flashing(tmp_path: Path) -> None:
    uf2 = tmp_path / "_main.uf2"
    uf2.write_bytes(b"UF2\n" * 100)
    verify_sha256(uf2, sha256_of(uf2).upper())
    with pytest.raises(ChecksumMismatchError):
        verify_sha256(uf2, "0" * 64)
