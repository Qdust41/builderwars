"""Read the user's sensor definitions off the target board(s) through the FREE-WILi.

    laptop (this code) --USB--> FREE-WILi --I2C/SPI/UART/GPIO--> target boards

The definitions come from the cloud (``GET /devices/{id}/sensors``, edited on the device page)
as :class:`device_protocol.sensors.SensorSpec`. Each sensor is polled at its own rate; a
sample only carries the sensors that were due. One sensor failing (wrong address, garbage
reply) is logged and skipped, while the others keep reading; losing the FREE-WILi itself
raises ``BoardUnavailableError`` like the plain FREE-WILi reader does.

``SimulatedConfiguredSensors`` produces made-up values for the same definitions, for
``builderwars run --simulate`` (no hardware), so the dashboard shows the real sensor names.
"""

from __future__ import annotations

import logging
import math
import random
import re
import time
from collections.abc import Callable, Sequence
from typing import Any

from board_runtime.hardware.freewili import FreeWiliSensors
from board_runtime.hardware.sensors import BoardUnavailableError
from device_protocol.schemas import MetricValue
from device_protocol.sensors import (
    GPIOBus,
    I2CBus,
    SensorDecodeError,
    SensorSpec,
    SPIBus,
    UARTBus,
    decode_bytes,
    parse_uart_reply,
    scale,
)

log = logging.getLogger(__name__)
# Per-sensor problems go to the logger the runtime forwards to the cloud log stream.
app_log = logging.getLogger("board_runtime.app")

REFRESH_INTERVAL_S = 30.0


class SensorReadError(Exception):
    """The FREE-WILi answered, but this one sensor could not be read. Others keep going."""


class _Scheduler:
    """Which sensors are due now, each at its own ``poll_interval_s``."""

    def __init__(self, specs: Sequence[SensorSpec], clock: Callable[[], float]) -> None:
        self._clock = clock
        self.specs: list[SensorSpec] = []
        self._next: dict[str, float] = {}
        self.replace(specs)

    def replace(self, specs: Sequence[SensorSpec]) -> None:
        self.specs = [s for s in specs if s.enabled]
        keep = {s.key for s in self.specs}
        self._next = {k: v for k, v in self._next.items() if k in keep}

    def due(self) -> list[SensorSpec]:
        now = self._clock()
        due = [s for s in self.specs if self._next.get(s.key, 0.0) <= now]
        for spec in due:
            self._next[spec.key] = now + spec.poll_interval_s
        return due


class ConfiguredSensors:
    """``SensorReader`` for user-defined sensors on a FREE-WILi.

    ``refresh`` (optional) returns the current definitions from the cloud; it is called every
    ``REFRESH_INTERVAL_S`` so sensors edited on the device page apply without a restart.
    """

    def __init__(
        self,
        specs: Sequence[SensorSpec],
        board: FreeWiliSensors,
        *,
        refresh: Callable[[], Sequence[SensorSpec]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.board = board
        self._schedule = _Scheduler(specs, clock)
        self._refresh = refresh
        self._clock = clock
        self._sleep = sleep
        self._last_refresh = clock()
        self._errors: dict[str, str] = {}
        self._uart_text = ""
        self._uart_ready = False

    @property
    def specs(self) -> list[SensorSpec]:
        return list(self._schedule.specs)

    @property
    def min_poll_interval_s(self) -> float | None:
        return min((s.poll_interval_s for s in self._schedule.specs), default=None)

    def read(self) -> dict[str, MetricValue]:
        self._maybe_refresh()
        due = self._schedule.due()
        if not due:
            return {}
        device = self.board.connect()
        readings: dict[str, MetricValue] = {}
        io_levels: tuple[int, ...] | None = None
        try:
            for spec in due:
                try:
                    if isinstance(spec.bus, GPIOBus):
                        if io_levels is None:  # one GPIO read serves every GPIO sensor
                            io_levels = self._get_io(device)
                        value = self._gpio(spec, spec.bus, io_levels)
                    else:
                        value = self.read_one(device, spec)
                except (SensorReadError, SensorDecodeError) as exc:
                    self._report(spec, str(exc))
                    continue
                self._recovered(spec)
                readings[spec.key] = value
        except BoardUnavailableError:
            raise
        except Exception as exc:  # serial errors surface as exceptions on unplug
            self.board.close()
            self._uart_ready = False
            raise BoardUnavailableError(
                f"lost the FREE-WILi while reading sensors ({type(exc).__name__}: {exc})",
                "was it unplugged or reset? It is reconnected automatically on the next read.",
            ) from exc
        return readings

    # -- one sensor --------------------------------------------------------------------------
    def read_one(self, device: Any, spec: SensorSpec) -> MetricValue:
        """Read one sensor now (also used by ``builderwars sensors --read``)."""
        bus = spec.bus
        if isinstance(bus, I2CBus):
            return self._i2c(device, spec, bus)
        if isinstance(bus, SPIBus):
            return self._spi(device, spec, bus)
        if isinstance(bus, UARTBus):
            return self._uart(device, spec, bus)
        return self._gpio(spec, bus, self._get_io(device))

    def _proc(self) -> Any:
        return self.board._processor("Main")

    def _i2c(self, device: Any, spec: SensorSpec, bus: I2CBus) -> MetricValue:
        for write in bus.setup_writes:
            _ok(
                device.write_i2c(bus.address, write.reg, bytes(write.data), self._proc()),
                f"I2C setup write to 0x{bus.address:02X} reg 0x{write.reg:02X}",
            )
        raw = _ok(
            device.read_i2c(bus.address, bus.reg, bus.length, self._proc()),
            f"I2C read of 0x{bus.address:02X} reg 0x{bus.reg:02X}",
        )
        return decode_bytes(_as_bytes(raw), spec.decode)

    def _spi(self, device: Any, spec: SensorSpec, bus: SPIBus) -> MetricValue:
        raw = _as_bytes(
            _ok(device.read_write_spi_data(bytes(bus.write), self._proc()), "SPI transfer")
        )
        window = raw[bus.read_offset : bus.read_offset + bus.length]
        return decode_bytes(window, spec.decode)

    def _get_io(self, device: Any) -> tuple[int, ...]:
        return tuple(_ok(device.get_io(self._proc()), "reading GPIO levels"))

    @staticmethod
    def _gpio(spec: SensorSpec, bus: GPIOBus, levels: tuple[int, ...]) -> MetricValue:
        if bus.pin >= len(levels):
            raise SensorReadError(
                f"the FREE-WILi reports {len(levels)} pins; GPIO{bus.pin} is not one"
            )
        return scale(int(levels[bus.pin]), spec.decode)

    def _uart(self, device: Any, spec: SensorSpec, bus: UARTBus) -> MetricValue:
        if not self._uart_ready:
            device.set_event_callback(self._on_event)
            _ok(device.enable_uart_events(True, self._proc()), "enabling UART events")
            self._uart_ready = True
        device.process_events()  # drop anything that arrived since the last query
        self._uart_text = ""
        if bus.command:
            _ok(device.write_uart(bus.command + bus.line_ending, self._proc()), "UART write")
        deadline = self._clock() + bus.timeout_s
        while True:
            device.process_events()
            # Wait for a complete line, so "T=2" + "3.5C" isn't read as 2.
            if "\n" in self._uart_text or "\r" in self._uart_text:
                return parse_uart_reply(self._uart_text, bus, spec.decode)
            if self._clock() >= deadline:
                break
            self._sleep(0.02)
        if self._uart_text:  # no line ending within the timeout: use what arrived
            return parse_uart_reply(self._uart_text, bus, spec.decode)
        raise SensorReadError(f"no UART reply within {bus.timeout_s:g} s")

    def _on_event(self, event_type: Any, frame: Any, data: Any) -> None:
        if "UART" not in str(getattr(event_type, "name", event_type)).upper():
            return
        chunk = getattr(data, "data", b"")
        if isinstance(chunk, (bytes, bytearray)):
            self._uart_text += chunk.decode("utf-8", errors="replace")
        elif isinstance(chunk, str):
            self._uart_text += chunk

    # -- bookkeeping -------------------------------------------------------------------------
    def _report(self, spec: SensorSpec, problem: str) -> None:
        if self._errors.get(spec.key) != problem:  # once per distinct problem, not per poll
            self._errors[spec.key] = problem
            app_log.warning("sensor %s (%s): %s", spec.key, spec.bus.protocol, problem)

    def _recovered(self, spec: SensorSpec) -> None:
        if self._errors.pop(spec.key, None) is not None:
            app_log.info("sensor %s is reading again", spec.key)

    def _maybe_refresh(self) -> None:
        if self._refresh is None or self._clock() - self._last_refresh < REFRESH_INTERVAL_S:
            return
        self._last_refresh = self._clock()
        try:
            specs = list(self._refresh())
        except Exception as exc:  # keep reading the old definitions
            log.debug("could not refresh sensor definitions: %s", exc)
            return
        before = {s.key: s for s in self._schedule.specs}
        self._schedule.replace(specs)
        after = {s.key: s for s in self._schedule.specs}
        if before != after:
            app_log.info(
                "sensor definitions changed; now reading %s",
                ", ".join(after) or "nothing (no enabled sensors)",
            )

    def close(self) -> None:
        self.board.close()


class SimulatedConfiguredSensors:
    """Made-up values for real sensor definitions (``--simulate``): no hardware involved."""

    def __init__(
        self,
        specs: Sequence[SensorSpec],
        *,
        seed: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._schedule = _Scheduler(specs, clock)
        self._rng = random.Random(seed)  # noqa: S311 - simulation only
        self._tick = 0

    @property
    def specs(self) -> list[SensorSpec]:
        return list(self._schedule.specs)

    @property
    def min_poll_interval_s(self) -> float | None:
        return min((s.poll_interval_s for s in self._schedule.specs), default=None)

    def read(self) -> dict[str, MetricValue]:
        self._tick += 1
        readings: dict[str, MetricValue] = {}
        for spec in self._schedule.due():
            if isinstance(spec.bus, GPIOBus):
                readings[spec.key] = int(self._rng.random() < 0.5)
                continue
            phase = (sum(map(ord, spec.key)) % 628) / 100
            base = 50 + 25 * math.sin(self._tick / 10 + phase) + self._rng.uniform(-1, 1)
            readings[spec.key] = round(base, 2)
        return readings


def _ok(result: Any, what: str) -> Any:
    """Unwrap a freewili ``Result``; an error answer becomes ``SensorReadError``."""
    if result.is_err():
        raise SensorReadError(f"{what} failed: {result.unwrap_err()}")
    return result.unwrap()


def _as_bytes(raw: Any) -> bytes:
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    if isinstance(raw, str):  # some firmware answers with hex text, e.g. "0A 1B"
        cleaned = re.sub(r"[^0-9a-fA-F]", "", raw)
        if len(cleaned) % 2:
            raise SensorReadError(f"unexpected answer {raw!r}")
        return bytes.fromhex(cleaned)
    if isinstance(raw, (list, tuple)):
        return bytes(int(b) & 0xFF for b in raw)
    raise SensorReadError(f"unexpected answer {raw!r}")
