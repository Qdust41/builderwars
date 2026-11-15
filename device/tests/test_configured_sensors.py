"""User-defined sensors read through a (fake) FREE-WILi, and the --simulate fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import pytest

from board_runtime.hardware import (
    BoardUnavailableError,
    ConfiguredSensors,
    FreeWiliSensors,
    SimulatedConfiguredSensors,
)
from device_protocol.sensor_presets import SENSOR_PRESETS
from device_protocol.sensors import SensorSpec


class _Ok:
    def __init__(self, value: Any) -> None:
        self._value = value

    def is_err(self) -> bool:
        return False

    def unwrap(self) -> Any:
        return self._value


class _Err:
    def __init__(self, why: str = "NAK") -> None:
        self.why = why

    def is_err(self) -> bool:
        return True

    def unwrap_err(self) -> str:
        return self.why


class EventType(Enum):
    UART1 = 1


@dataclass
class UartData:
    data: bytes


class FakeBoard:
    """Answers like a FREE-WILi with a TMP102 at 0x48, an MCP3008 on SPI and a UART device."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.unplugged = False
        self._callback: Any = None
        self._pending: list[bytes] = []

    def write_i2c(self, address: int, reg: int, data: bytes, processor: Any) -> Any:
        self.calls.append(("write_i2c", address, reg, data))
        return _Ok("OK")

    def read_i2c(self, address: int, reg: int, size: int, processor: Any) -> Any:
        if self.unplugged:
            raise OSError("device disconnected")
        self.calls.append(("read_i2c", address, reg, size))
        if address != 0x48:
            return _Err(f"no ACK from 0x{address:02X}")
        return _Ok(bytes([0x19, 0x00]))  # 25 °C

    def read_write_spi_data(self, data: bytes, processor: Any) -> Any:
        self.calls.append(("spi", data))
        return _Ok(bytes([0xFF, 0xFE, 0x00]))  # MCP3008 half scale

    def get_io(self, processor: Any) -> Any:
        self.calls.append(("get_io",))
        return _Ok(tuple(1 if pin == 26 else 0 for pin in range(32)))

    def set_event_callback(self, callback: Any) -> None:
        self._callback = callback

    def enable_uart_events(self, enable: bool, processor: Any) -> Any:
        return _Ok("OK")

    def write_uart(self, data: str, processor: Any) -> Any:
        self.calls.append(("uart", data))
        if data.startswith("READ?"):
            self._pending += [b"T=2", b"3.5C\r\n"]  # reply arrives in two chunks
        return _Ok("OK")

    def process_events(self) -> None:
        if self._pending:
            self._callback(EventType.UART1, None, UartData(self._pending.pop(0)))


def _spec(preset_id: str, **change: Any) -> SensorSpec:
    preset = next(p for p in SENSOR_PRESETS if p.id == preset_id)
    return SensorSpec.model_validate({**preset.sensor.model_dump(mode="json"), **change})


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _reader(
    board: FakeBoard, specs: list[SensorSpec], clock: Clock, **kw: Any
) -> ConfiguredSensors:
    return ConfiguredSensors(specs, FreeWiliSensors(board), clock=clock, sleep=clock.sleep, **kw)


def test_reads_each_protocol_through_the_freewili() -> None:
    board, clock = FakeBoard(), Clock()
    specs = [
        _spec("tmp102-temp"),
        _spec("mcp3008-ch0"),
        _spec("gpio-digital-in"),
        _spec("uart-query"),
    ]
    readings = _reader(board, specs, clock).read()
    assert readings == {
        "tmp102_temp_c": 25.0,
        "mcp3008_ch0_v": 1.65,
        "digital_in": 1,
        "uart_value": 23.5,
    }
    assert ("uart", "READ?\n") in board.calls


def test_setup_writes_go_before_the_read() -> None:
    board, clock = FakeBoard(), Clock()
    spec = _spec("ads1115-ain0")
    _reader(board, [spec], clock).read()
    assert board.calls[:2] == [
        ("write_i2c", 0x48, 0x01, bytes([0xC2, 0x83])),
        ("read_i2c", 0x48, 0x00, 2),
    ]


def test_each_sensor_polls_at_its_own_rate() -> None:
    board, clock = FakeBoard(), Clock()
    fast = _spec("tmp102-temp", poll_interval_s=1)
    slow = _spec("gpio-digital-in", poll_interval_s=5)
    reader = _reader(board, [fast, slow], clock)
    assert set(reader.read()) == {"tmp102_temp_c", "digital_in"}
    clock.now += 1
    assert set(reader.read()) == {"tmp102_temp_c"}
    clock.now += 0.5
    assert reader.read() == {}
    clock.now += 4
    assert set(reader.read()) == {"tmp102_temp_c", "digital_in"}


def test_one_bad_sensor_is_logged_once_and_the_rest_keep_reading(
    caplog: pytest.LogCaptureFixture,
) -> None:
    board, clock = FakeBoard(), Clock()
    wrong = _spec(
        "tmp102-temp",
        key="wrong_addr",
        bus={"protocol": "i2c", "address": 0x49, "reg": 0, "length": 2},
    )
    reader = _reader(board, [wrong, _spec("gpio-digital-in")], clock)
    with caplog.at_level(logging.WARNING, logger="board_runtime.app"):
        assert reader.read() == {"digital_in": 1}
        clock.now += 1
        assert reader.read() == {"digital_in": 1}
    problems = [r.getMessage() for r in caplog.records if "wrong_addr" in r.getMessage()]
    assert len(problems) == 1
    assert "no ACK from 0x49" in problems[0]


def test_disabled_sensors_are_not_read() -> None:
    board, clock = FakeBoard(), Clock()
    reader = _reader(board, [_spec("tmp102-temp", enabled=False)], clock)
    assert reader.read() == {}
    assert board.calls == []


def test_unplugging_the_freewili_makes_the_board_unavailable() -> None:
    board, clock = FakeBoard(), Clock()
    board.unplugged = True
    with pytest.raises(BoardUnavailableError, match="lost the FREE-WILi"):
        _reader(board, [_spec("tmp102-temp")], clock).read()


def test_definitions_refresh_from_the_cloud() -> None:
    board, clock = FakeBoard(), Clock()
    current = [_spec("tmp102-temp")]
    reader = _reader(board, list(current), clock, refresh=lambda: current)
    assert set(reader.read()) == {"tmp102_temp_c"}
    current = [_spec("gpio-digital-in")]
    clock.now += 31
    assert set(reader.read()) == {"digital_in"}


def test_simulation_uses_the_defined_sensor_names() -> None:
    clock = Clock()
    sim = SimulatedConfiguredSensors(
        [_spec("tmp102-temp"), _spec("gpio-digital-in")], seed=1, clock=clock
    )
    readings = sim.read()
    assert set(readings) == {"tmp102_temp_c", "digital_in"}
    assert readings["digital_in"] in (0, 1)
