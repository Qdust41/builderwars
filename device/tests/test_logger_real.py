"""``run --logger real``: the logger_real.py way of reading a FREE-WILi, against a fake onewili."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import board_runtime.hardware.logger_real as lr
from board_runtime.batching import TelemetryBatcher
from board_runtime.cloud.files import read_messages
from board_runtime.hardware.logger_real import (
    LOGGER_CSV_COLUMNS,
    LoggerRealSensors,
    decode_imu,
    mpu6050_temp_c,
    readings_from_csv_row,
)
from board_runtime.hardware.sensors import BoardUnavailableError
from device_protocol import DeviceEnvelope, MessageType
from device_protocol.envelopes import MAX_PAYLOAD_BYTES

# One real row from the friend's combined_gpio_imu.csv.
IMU_HEX = "e9301f9837dc07a0ffcc0161004e"
IMU_VALUES = [-5840, 8088, 14300, 1952, -52, 353, 78]
GPIO_RAW = 204800  # pins 13, 16 and 17 high


class Ok:
    def __init__(self, value: Any) -> None:
        self.ok_value = value

    def is_err(self) -> bool:
        return False


class Err:
    def __init__(self, error: str) -> None:
        self.err_value = error

    def is_err(self) -> bool:
        return True

    def __str__(self) -> str:
        return f"Err({self.err_value!r})"


class FakeOneWili:
    def __init__(self) -> None:
        self.gpio_result: Any = Ok(GPIO_RAW)
        self.imu_result: Any = Ok(bytes.fromhex(IMU_HEX))
        self.calls: list[tuple[str, Any]] = []
        self.raise_on_read: Exception | None = None
        outer = self

        class I2C:
            def i2c_slave_enable(self, address: int) -> Any:
                outer.calls.append(("slave", address))
                return Ok(None)

            def i2c_write(self, address: int, register: int, data: bytes) -> Any:
                outer.calls.append(("write", (address, register, data)))
                return Ok(None)

            def _call(
                self, hotkey: str, args: list[str], returns: list[str], timeout: float
            ) -> Any:
                outer.calls.append(("read", (hotkey, args)))
                if outer.raise_on_read:
                    raise outer.raise_on_read
                return outer.imu_result

        class GPIO:
            def read_all(self) -> Any:
                return outer.gpio_result

        self.io = SimpleNamespace(i2c=I2C(), gpio=GPIO())


def test_decode_matches_the_scripts_csv() -> None:
    assert decode_imu(bytes.fromhex(IMU_HEX)) == IMU_VALUES
    assert decode_imu(b"\x00" * 3) is None
    assert mpu6050_temp_c(1952) == 42.27


def test_setup_then_readings_and_csv_like_the_script(tmp_path: Path) -> None:
    fake = FakeOneWili()
    out = tmp_path / "log.csv"
    sensors = LoggerRealSensors(fake, csv_path=out)
    readings = sensors.read()
    sensors.read()
    sensors.close()

    assert fake.calls[0] == ("slave", 0)
    assert fake.calls[1] == ("write", (0x68, 0x6B, b"\x00"))
    assert fake.calls[2] == ("read", ("r", ["68", "3B", "14"]))
    assert readings["gpio_raw"] == GPIO_RAW
    assert [readings[f"gpio_{i}"] for i in (12, 13, 16, 17, 18)] == [0, 1, 1, 1, 0]
    assert readings["accel_x_raw"] == -5840
    assert readings["gyro_z_raw"] == 78
    assert readings["imu_temp_c"] == 42.27
    assert all(isinstance(k, str) and k == k.lower() for k in readings)

    rows = list(csv.reader(out.open()))
    assert tuple(rows[0]) == LOGGER_CSV_COLUMNS
    assert len(rows) == 3
    row = dict(zip(rows[0], rows[1], strict=True))
    assert row["gpio_raw"] == str(GPIO_RAW)
    assert row["GPIO13"] == "1"
    assert row["imu_raw_hex"] == IMU_HEX
    assert row["imu_byte_0"] == "233"
    assert row["temperature_raw"] == "1952"


def test_matches_the_columns_of_the_friends_script() -> None:
    script = Path(__file__).parents[2] / "scripts/wili_code/src/logger_real.py"
    if not script.is_file():
        pytest.skip("script not in this checkout")
    text = script.read_text()
    for name in ("timestamp", "elapsed_s", "gpio_raw", "imu_raw_hex", "accel_x_raw", "gyro_z_raw"):
        assert f'"{name}"' in text


def test_one_failing_read_sends_the_other(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeOneWili()
    fake.imu_result = Err("timeout")
    sensors = LoggerRealSensors(fake)
    readings = sensors.read()
    assert "gpio_raw" in readings
    assert "accel_x_raw" not in readings
    sensors.read()
    warnings = [r for r in caplog.records if "IMU" in r.getMessage()]
    assert len(warnings) == 1  # once, not every sample

    fake.imu_result = Ok(bytes.fromhex(IMU_HEX))
    fake.gpio_result = Err("timeout")
    readings = sensors.read()
    assert "accel_x_raw" in readings
    assert "gpio_raw" not in readings


def test_both_failing_is_board_unavailable() -> None:
    fake = FakeOneWili()
    fake.gpio_result = Err("timeout waiting for response")
    fake.imu_result = Err("timeout")
    with pytest.raises(BoardUnavailableError):
        LoggerRealSensors(fake).read()


def test_serial_exception_is_board_unavailable() -> None:
    fake = FakeOneWili()
    fake.raise_on_read = OSError("device disconnected")
    with pytest.raises(BoardUnavailableError, match="lost the FREE-WILi"):
        LoggerRealSensors(fake).read()


def test_missing_onewili_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing() -> Any:
        raise lr.OneWiliNotInstalledError()

    monkeypatch.setattr(lr, "import_onewili", missing)
    with pytest.raises(lr.OneWiliNotInstalledError) as info:
        LoggerRealSensors().connect()
    assert "git+https://github.com/freewili/onewili" in info.value.hint


def test_csv_row_without_imu() -> None:
    row = {"gpio_raw": "5", "imu_error": "Err('timeout')", **{n: "" for n in lr.IMU_VALUES}}
    readings = readings_from_csv_row(row)
    assert readings["gpio_0"] == 1
    assert readings["gpio_1"] == 0
    assert readings["gpio_2"] == 1
    assert "accel_x_raw" not in readings


def test_batches_of_wide_samples_stay_under_the_size_limit() -> None:
    from datetime import UTC, datetime, timedelta

    readings = {**{f"gpio_{i}": 1 for i in range(32)}, "gpio_raw": 4294967295}
    readings.update({name: -32768 for name in lr.IMU_VALUES})
    readings["imu_temp_c"] = 36.53
    batcher = TelemetryBatcher(window_s=5.0, max_samples=32)
    start = datetime(2026, 11, 15, tzinfo=UTC)
    batches = []
    for i in range(64):
        batch = batcher.add(readings, at=start + timedelta(seconds=i / 10), now=0.0)
        if batch:
            batches.append(batch)
    batches.append(batcher.flush())
    assert sum(len(b["samples"]) for b in batches) == 64
    for batch in batches:
        assert len(json.dumps(batch, separators=(",", ":")).encode()) <= MAX_PAYLOAD_BYTES
        DeviceEnvelope.new(device_id="dev_x", message_type=MessageType.TELEMETRY, payload=batch)


def _write_logger_csv(path: Path, rows: int) -> None:
    fake = FakeOneWili()
    sensors = LoggerRealSensors(fake, csv_path=path)
    for _ in range(rows):
        sensors.read()
    sensors.close()


def test_upload_reads_a_logger_csv_as_telemetry(tmp_path: Path) -> None:
    path = tmp_path / "combined_gpio_imu.csv"
    _write_logger_csv(path, 70)
    read = read_messages(path, "dev_abc")
    assert not read.skipped
    assert read.messages
    total = 0
    for message in read.messages:
        assert message["topic"].endswith("/telemetry")
        envelope = DeviceEnvelope.model_validate(message["payload"])
        assert envelope.device_id == "dev_abc"
        total += len(envelope.payload["samples"])
        assert envelope.payload["samples"][0]["readings"]["accel_x_raw"] == -5840
    assert total == 70
    # Same file again: same message ids, so the API stores it once.
    again = read_messages(path, "dev_abc")
    ids = [m["payload"]["message_id"] for m in read.messages]
    assert ids == [m["payload"]["message_id"] for m in again.messages]


def test_upload_reads_the_scripts_own_csv(tmp_path: Path) -> None:
    header = ",".join(LOGGER_CSV_COLUMNS)
    bits = ",".join(str((GPIO_RAW >> b) & 1) for b in range(32))
    imu_bytes = ",".join(str(b) for b in bytes.fromhex(IMU_HEX))
    values = ",".join(str(v) for v in IMU_VALUES)
    line = f"2026-11-15T10:55:10.007541,0.000313,{GPIO_RAW},,{bits},{IMU_HEX},,{imu_bytes},{values}"
    failed = (
        "2026-11-15T10:55:10.107630,0.1,," + "Err('timeout')," + "," * 31 + ",Err('x')" + "," * 21
    )
    path = tmp_path / "combined.csv"
    path.write_text(f"{header}\n{line}\n{failed}\n")
    read = read_messages(path, "dev_abc")
    assert len(read.messages) == 1
    assert len(read.skipped) == 1
    assert "no readings" in read.skipped[0]
    sample = read.messages[0]["payload"]["payload"]["samples"][0]
    assert sample["readings"]["gpio_13"] == 1
    assert "+" in sample["ts"] or sample["ts"].endswith("Z") or "-" in sample["ts"][19:]


def test_run_logger_real_sends_the_readings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    import board_runtime.cli as cli

    fake = FakeOneWili()
    fake.close = lambda: None  # type: ignore[attr-defined]
    module = SimpleNamespace(connect=lambda: fake, OneWili=None)
    monkeypatch.setattr(lr, "import_onewili", lambda: module)
    monkeypatch.setenv("DEVICE_TRANSPORT", "stdout")
    monkeypatch.setenv("BUILDERWARS_LOG_CSV", "off")
    monkeypatch.setenv("DEVICE_BATCH_WINDOW_S", "0.001")
    out = tmp_path / "run.csv"
    code = cli.main(
        [
            "--state-dir",
            str(tmp_path),
            "run",
            "--logger",
            "real",
            "-n",
            "2",
            "-i",
            "0.01",
            "--csv",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    telemetry = [
        json.loads(line)
        for line in captured.out.splitlines()
        if line.startswith("{") and '"telemetry"' in line
    ]
    readings = [s["readings"] for t in telemetry for s in t["payload"]["payload"]["samples"]]
    assert readings
    assert readings[0]["accel_x_raw"] == -5840
    assert readings[0]["gpio_13"] == 1
    assert len(list(csv.reader(out.open()))) == 3


def test_run_logger_and_simulate_conflict(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    import board_runtime.cli as cli

    assert cli.main(["--state-dir", str(tmp_path), "run", "--logger", "real", "--simulate"]) == 2
    assert "don't go together" in capsys.readouterr().err
