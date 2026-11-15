"""Sensor definitions, decoding and the common-parts presets."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from device_protocol.sensor_presets import SENSOR_PRESETS
from device_protocol.sensors import (
    SensorDecode,
    SensorDecodeError,
    SensorSpec,
    UARTBus,
    decode_bytes,
    parse_uart_reply,
)


def _preset(preset_id: str) -> SensorSpec:
    return next(p.sensor for p in SENSOR_PRESETS if p.id == preset_id)


@pytest.mark.parametrize(
    ("preset_id", "raw", "expected"),
    [
        ("tmp102-temp", bytes([0x19, 0x00]), 25.0),  # datasheet table: 0x190 = 25 °C
        ("tmp102-temp", bytes([0xE7, 0x00]), -25.0),  # 0xE70 = -25 °C
        ("lm75-temp", bytes([0x19, 0x00]), 25.0),
        ("mcp9808-temp", bytes([0xC1, 0x90]), 25.0),  # flag bits masked off
        ("max31855-thermocouple", bytes([0x06, 0x40, 0x00, 0x00]), 100.0),
        ("max6675-thermocouple", bytes([0x0C, 0x80]), 100.0),
        ("ina219-bus-voltage", bytes([0x5D, 0xC0]), 12.0),  # 3000 * 4 mV
        ("ads1115-ain0", bytes([0x40, 0x00]), 2.048),
        ("mcp3008-ch0", bytes([0xFE, 0x00]), 1.65),  # upper bits are junk; 0x200 = half
        ("mpu6050-accel-x", bytes([0x40, 0x00]), 1.0),
        ("adxl345-x", bytes([0x00, 0x01]), 1.0),  # little endian 256 * 3.9 mg ~ 1 g
    ],
)
def test_presets_decode_datasheet_examples(preset_id: str, raw: bytes, expected: float) -> None:
    value = decode_bytes(raw, _preset(preset_id).decode)
    assert value == pytest.approx(expected, abs=0.01)


def test_every_preset_is_a_valid_sensor_with_a_unique_id() -> None:
    ids = [p.id for p in SENSOR_PRESETS]
    assert len(ids) == len(set(ids))
    for preset in SENSOR_PRESETS:
        SensorSpec.model_validate(preset.sensor.model_dump(mode="json"))


def test_integers_stay_integers_without_scaling() -> None:
    assert decode_bytes(b"\x60", SensorDecode(data_type="u8")) == 96
    assert isinstance(decode_bytes(b"\x60", SensorDecode(data_type="u8")), int)


def test_float_decoding_and_short_reads() -> None:
    assert decode_bytes(bytes.fromhex("41c80000"), SensorDecode(data_type="f32_be")) == 25.0
    with pytest.raises(SensorDecodeError):
        decode_bytes(b"\x01", SensorDecode(data_type="u16_be"))
    with pytest.raises(SensorDecodeError):
        decode_bytes(bytes.fromhex("7fc00000"), SensorDecode(data_type="f32_be"))  # NaN


def test_uart_replies() -> None:
    bus = UARTBus(command="READ?")
    assert parse_uart_reply("T=23.5C\r\n", bus, SensorDecode()) == 23.5
    assert parse_uart_reply("-4", bus, SensorDecode(scale=2)) == -8
    custom = UARTBus(response_pattern=r"V:(0x[0-9a-f]+)")
    assert parse_uart_reply("ok V:0x1f", custom, SensorDecode()) == 31
    with pytest.raises(SensorDecodeError):
        parse_uart_reply("ERR", bus, SensorDecode())


def test_unknown_fields_are_ignored_for_the_cli() -> None:
    spec = SensorSpec.model_validate(
        {
            "id": "sen_1",
            "key": "x",
            "name": "X",
            "bus": {"protocol": "gpio", "pin": 3},
        }
    )
    assert spec.bus.protocol == "gpio"


def test_spi_read_window_must_fit() -> None:
    with pytest.raises(ValidationError, match="read_offset"):
        SensorSpec.model_validate(
            {
                "key": "x",
                "name": "X",
                "bus": {"protocol": "spi", "write": [1, 2], "read_offset": 1, "length": 2},
            }
        )
