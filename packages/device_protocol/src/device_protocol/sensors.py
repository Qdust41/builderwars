"""Sensor definitions: how the host reads one value off the target board through the FREE-WILi.

The test setup is a chain: the user's laptop runs the ``builderwars`` CLI, a FREE-WILi is
plugged into the laptop over USB, and the board under test is wired to the FREE-WILi's I2C,
SPI, UART or GPIO pins. Users define sensors in the web app; the API stores them; the CLI
downloads them and reads each one through the FREE-WILi. These models are shared by the API
(validation), the CLI (parsing what it downloads) and the decoder below, so a definition means
the same thing everywhere.

Python 3.10-safe: the host runtime imports this module.
"""

from __future__ import annotations

import re
import struct
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from device_protocol.schemas import METRIC_NAME_PATTERN

SensorProtocol = Literal["i2c", "spi", "uart", "gpio"]
SENSOR_PROTOCOLS: Final[tuple[str, ...]] = ("i2c", "spi", "uart", "gpio")

DataType = Literal[
    "u8",
    "i8",
    "u16_be",
    "u16_le",
    "i16_be",
    "i16_le",
    "u32_be",
    "u32_le",
    "i32_be",
    "i32_le",
    "f32_be",
    "f32_le",
]
# data type -> (struct format, size in bytes)
DATA_TYPE_FORMATS: Final[dict[str, tuple[str, int]]] = {
    "u8": (">B", 1),
    "i8": (">b", 1),
    "u16_be": (">H", 2),
    "u16_le": ("<H", 2),
    "i16_be": (">h", 2),
    "i16_le": ("<h", 2),
    "u32_be": (">I", 4),
    "u32_le": ("<I", 4),
    "i32_be": (">i", 4),
    "i32_le": ("<i", 4),
    "f32_be": (">f", 4),
    "f32_le": ("<f", 4),
}

# First number in a UART reply when no pattern is given: "T=23.5C" -> 23.5.
DEFAULT_UART_PATTERN: Final[str] = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"

MAX_SENSORS_PER_DEVICE: Final[int] = 32

Byte = Annotated[int, Field(ge=0, le=255)]


class SensorDecodeError(ValueError):
    """The board answered, but the answer can't be turned into a number with this definition."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class I2CWrite(_Model):
    """One register write sent before reading, e.g. to wake a sensor or start a conversion."""

    reg: Byte = Field(description="register to read (or write), e.g. 0x00")
    data: list[Byte] = Field(min_length=1, max_length=16)


class I2CBus(_Model):
    """Read ``length`` bytes from register ``reg`` of the chip at 7-bit ``address``."""

    protocol: Literal["i2c"] = "i2c"
    address: int = Field(ge=0, le=0x7F, description="7-bit I2C address, e.g. 0x48")
    reg: Byte = Field(description="register to read (or write), e.g. 0x00")
    length: int = Field(default=1, ge=1, le=8, description="bytes to read")
    setup_writes: list[I2CWrite] = Field(
        default_factory=list,
        max_length=8,
        description="written before every read, in order (e.g. start a conversion)",
    )


class SPIBus(_Model):
    """Clock ``write`` out on SPI1 (chip select GPIO13) and keep ``length`` bytes of the
    answer starting at ``read_offset`` (byte 0 usually echoes the command)."""

    protocol: Literal["spi"] = "spi"
    write: list[Byte] = Field(min_length=1, max_length=32, description="bytes to send")
    read_offset: int = Field(default=1, ge=0, le=31)
    length: int = Field(default=1, ge=1, le=8)
    # Recorded for the person wiring the board; the freewili library cannot set these from
    # the host, so they are configured on the FREE-WILi itself.
    mode: Literal[0, 1, 2, 3] = 0
    clock_hz: int | None = Field(default=None, ge=1_000, le=50_000_000)

    @model_validator(mode="after")
    def _fits(self) -> SPIBus:
        if self.read_offset + self.length > len(self.write):
            raise ValueError(
                "read_offset + length must not exceed the number of bytes sent: SPI only "
                "clocks in as many bytes as it clocks out (pad `write` with 0x00)"
            )
        return self


class GPIOBus(_Model):
    """The level (0 or 1) of one FREE-WILi GPIO pin wired to the target board."""

    protocol: Literal["gpio"] = "gpio"
    pin: int = Field(ge=0, le=63, description="FREE-WILi GPIO number, e.g. 26")


class UARTBus(_Model):
    """Send ``command`` on UART1 and pull a number out of the reply with ``response_pattern``
    (its first group, or the whole match). An empty command just listens."""

    protocol: Literal["uart"] = "uart"
    command: str = Field(default="", max_length=64)
    line_ending: Literal["", "\n", "\r\n", "\r"] = "\n"
    response_pattern: str | None = Field(default=None, max_length=200)
    timeout_s: float = Field(default=0.5, ge=0.05, le=5)
    # Recorded for the person wiring the board; set on the FREE-WILi itself.
    baud: int | None = Field(default=None, ge=300, le=3_000_000)

    @field_validator("response_pattern")
    @classmethod
    def _compiles(cls, value: str | None) -> str | None:
        if value:
            try:
                compiled = re.compile(value)
            except re.error as exc:
                raise ValueError(
                    f"response_pattern is not a valid regular expression: {exc}"
                ) from None
            if compiled.groups > 1:
                raise ValueError("response_pattern may have at most one capture group")
        return value or None


SensorBus = Annotated[I2CBus | SPIBus | UARTBus | GPIOBus, Field(discriminator="protocol")]


class SensorDecode(_Model):
    """Raw bytes -> number: unpack ``data_type``, then ``(raw & bit_mask) >> bit_shift``,
    then ``value * scale + offset``. GPIO and UART skip the unpack step."""

    data_type: DataType = "u8"
    bit_mask: int | None = Field(default=None, ge=0, le=0xFFFFFFFF)
    bit_shift: int = Field(default=0, ge=0, le=31)
    scale: float = 1.0
    offset: float = 0.0
    decimals: int | None = Field(default=None, ge=0, le=9, description="round the result")

    @property
    def size(self) -> int:
        return DATA_TYPE_FORMATS[self.data_type][1]


class SensorSpec(BaseModel):
    """Everything the host needs to read one sensor. Unknown fields (the API adds ``id`` and
    timestamps) are ignored so an older CLI keeps working against a newer API."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    key: str = Field(
        pattern=METRIC_NAME_PATTERN,
        description="reading name on the dashboard and in telemetry, e.g. board_temp_c",
    )
    name: str = Field(min_length=1, max_length=80)
    unit: str | None = Field(default=None, max_length=16)
    poll_interval_s: float = Field(default=1.0, ge=0.1, le=3600)
    enabled: bool = True
    bus: SensorBus
    decode: SensorDecode = Field(default_factory=SensorDecode)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("unit")
    @classmethod
    def _strip_unit(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @model_validator(mode="after")
    def _length_fits_type(self) -> SensorSpec:
        if isinstance(self.bus, (I2CBus, SPIBus)) and self.bus.length < self.decode.size:
            raise ValueError(
                f"{self.decode.data_type} needs {self.decode.size} bytes but the "
                f"{self.bus.protocol} read only returns {self.bus.length}"
            )
        if self.decode.data_type.startswith("f") and self.decode.bit_mask is not None:
            raise ValueError("bit_mask only applies to integer data types")
        return self


def scale(value: float, decode: SensorDecode) -> float | int:
    """Apply ``scale``/``offset``/``decimals``; integers stay integers when nothing changes."""
    if decode.scale == 1.0 and decode.offset == 0.0 and isinstance(value, int):
        return value
    result = value * decode.scale + decode.offset
    if decode.decimals is not None:
        result = round(result, decode.decimals)
    return result


def decode_bytes(raw: bytes, decode: SensorDecode) -> float | int:
    """Turn bytes read over I2C/SPI into the sensor's value."""
    fmt, size = DATA_TYPE_FORMATS[decode.data_type]
    if len(raw) < size:
        raise SensorDecodeError(
            f"expected at least {size} bytes for {decode.data_type}, got {len(raw)}"
        )
    value: Any = struct.unpack(fmt, bytes(raw[:size]))[0]
    if isinstance(value, int):
        if decode.bit_mask is not None:
            value &= decode.bit_mask
        value >>= decode.bit_shift
    elif value != value or value in (float("inf"), float("-inf")):
        raise SensorDecodeError(f"{decode.data_type} decoded to {value}, not a finite number")
    return scale(value, decode)


def parse_uart_reply(text: str, bus: UARTBus, decode: SensorDecode) -> float | int:
    """Pull the value out of a UART reply."""
    match = re.search(bus.response_pattern or DEFAULT_UART_PATTERN, text)
    if match is None:
        raise SensorDecodeError(f"no value in UART reply {text[:80]!r}")
    token = match.group(1) if match.re.groups else match.group(0)
    try:
        is_int = re.fullmatch(r"[-+]?(0x[0-9a-fA-F]+|\d+)", token) is not None
        number: float | int = int(token, 0) if is_int else float(token)
    except (TypeError, ValueError):
        raise SensorDecodeError(f"{token!r} in the UART reply is not a number") from None
    return scale(number, decode)


__all__ = [
    "DATA_TYPE_FORMATS",
    "DEFAULT_UART_PATTERN",
    "MAX_SENSORS_PER_DEVICE",
    "SENSOR_PROTOCOLS",
    "DataType",
    "GPIOBus",
    "I2CBus",
    "I2CWrite",
    "SPIBus",
    "SensorBus",
    "SensorDecode",
    "SensorDecodeError",
    "SensorProtocol",
    "SensorSpec",
    "UARTBus",
    "decode_bytes",
    "parse_uart_reply",
    "scale",
]
