"""FREE-WILi board I/O over USB serial (decision #1).

Wraps the vendor's ``freewili`` Python package (PyPI, MIT, Python 3.10+). Install it on the
host with ``pip install freewili==0.0.51``; it is deliberately not a locked extra (it pins
typing-extensions exactly). This is the only module that touches USB/serial.

NOTE: the decisions doc names ``onewili``; that package is not on PyPI. The published vendor
library is ``freewili`` (github.com/freewili/freewili-python), which provides the same
``pyfwfinder`` discovery + serial ``FreeWili`` device API, so it is used here. Swap the import
if ``onewili`` turns out to be required.

What is read is a PLACEHOLDER until spec 02 decides which sensors matter: the main CPU's GPIO
levels and the display CPU's buttons. Not yet run against real hardware.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from board_runtime.hardware.sensors import BoardUnavailableError
from device_protocol.schemas import MetricValue

log = logging.getLogger(__name__)


class _Result(Protocol):
    """Shape of ``result.Result`` as returned by the freewili package."""

    def is_err(self) -> bool: ...
    def unwrap(self) -> Any: ...
    def unwrap_err(self) -> Any: ...


class FreeWiliSensors:
    """``SensorReader`` backed by a FREE-WILi attached to this host.

    ``device`` lets tests inject a fake; normally the first attached board is discovered.
    Reconnects lazily: if a read fails the device is dropped and re-discovered next time.
    """

    def __init__(self, device: Any | None = None) -> None:
        self._device = device
        self._injected = device is not None

    def _module(self) -> Any:
        try:
            import freewili
            from freewili.types import FreeWiliProcessorType
        except ImportError as exc:  # pragma: no cover - host-only dependency
            raise RuntimeError(
                "install the vendor package on the host: pip install freewili==0.0.51"
            ) from exc
        return freewili, FreeWiliProcessorType

    def _processor(self, name: str) -> Any:
        if self._injected:
            return name
        _, processor_type = self._module()
        return getattr(processor_type, name)

    def _connect(self) -> Any:
        if self._device is not None:
            return self._device
        freewili, _ = self._module()
        found: _Result = freewili.FreeWili.find_first()
        if found.is_err():
            raise BoardUnavailableError(f"no FREE-WILi found: {found.unwrap_err()}")
        device = found.unwrap()
        opened: _Result = device.open()
        if opened.is_err():
            raise BoardUnavailableError(f"could not open FREE-WILi: {opened.unwrap_err()}")
        self._device = device
        return device

    def read(self) -> dict[str, MetricValue]:
        device = self._connect()
        try:
            io: _Result = device.get_io(self._processor("Main"))
            buttons: _Result = device.read_all_buttons(self._processor("Display"))
        except Exception as exc:  # serial errors surface as exceptions on unplug
            self.close()
            raise BoardUnavailableError(f"FREE-WILi read failed: {exc}") from exc
        if io.is_err() or buttons.is_err():
            self.close()
            raise BoardUnavailableError("FREE-WILi returned an error reading I/O")

        readings: dict[str, MetricValue] = {
            f"io_{index}": int(level) for index, level in enumerate(io.unwrap())
        }
        for color, pressed in buttons.unwrap().items():
            name = getattr(color, "name", str(color)).lower()
            readings[f"button_{name}"] = bool(pressed)
        return readings

    def close(self) -> None:
        if self._device is not None and not self._injected:
            try:
                self._device.close()
            except Exception:  # pragma: no cover - best effort on a dead port
                log.debug("ignoring error while closing FREE-WILi", exc_info=True)
            self._device = None
