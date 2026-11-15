"""FREE-WILi board I/O over USB serial (decision #1).

Wraps the vendor's ``freewili`` Python package (PyPI, MIT, Python 3.10+). In this repo it is a
root workspace dependency (``uv sync``); on a bare host install it with
``pip install freewili==0.0.51``. This is the only module that touches the board over USB.

NOTE: the decisions doc names ``onewili``; the published vendor library used here is
``freewili`` (github.com/freewili/freewili-python), which provides ``pyfwfinder`` discovery +
the serial ``FreeWili`` device API.

What is read is a PLACEHOLDER until spec 02 decides which sensors matter: the main CPU's GPIO
levels and the display CPU's buttons.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from board_runtime.hardware.ports import PortProblem, check_port, open_error_hint, same_port
from board_runtime.hardware.sensors import BoardUnavailableError
from device_protocol.schemas import MetricValue

log = logging.getLogger(__name__)

INSTALL_HINT = (
    "in this repo run `uv sync` (it is a workspace dependency); "
    "on a bare host: pip install freewili==0.0.51"
)


class FreeWiliNotInstalledError(RuntimeError):
    """The vendor ``freewili`` package is missing. Fatal: not a transient board problem."""

    def __init__(self) -> None:
        super().__init__(f"the 'freewili' Python package is not installed ({INSTALL_HINT})")
        self.hint = INSTALL_HINT


class _Result(Protocol):
    """Shape of ``result.Result`` as returned by the freewili package."""

    def is_err(self) -> bool: ...
    def unwrap(self) -> Any: ...
    def unwrap_err(self) -> Any: ...


@dataclass(frozen=True)
class BoardInfo:
    """What USB discovery knows about one attached board."""

    name: str
    serial: str
    kind: str
    main_port: str | None
    display_port: str | None

    @property
    def ports(self) -> tuple[str, ...]:
        return tuple(p for p in (self.main_port, self.display_port) if p)

    def describe(self) -> str:
        ports = ", ".join(
            f"{label} {port}"
            for label, port in (("main", self.main_port), ("display", self.display_port))
            if port
        )
        return f"{self.name} (serial {self.serial}, {ports or 'no serial ports'})"


def import_freewili() -> tuple[Any, Any]:
    """Return ``(freewili, FreeWiliProcessorType)``; raise ``FreeWiliNotInstalledError``."""
    try:
        import freewili
        from freewili.types import FreeWiliProcessorType
    except ImportError as exc:  # pragma: no cover - host-only dependency
        raise FreeWiliNotInstalledError() from exc
    return freewili, FreeWiliProcessorType


def _safe(getter: Any) -> Any:
    try:
        return getter()
    except Exception:  # vendor properties can raise on half-enumerated devices
        return None


def board_info(board: Any) -> BoardInfo:
    device: Any = getattr(board, "device", None)
    main = _safe(lambda: board.main)
    display = _safe(lambda: board.display)
    kind = _safe(lambda: device.device_type.name) or "unknown"
    return BoardInfo(
        name=str(_safe(lambda: device.name) or "FREE-WILi"),
        serial=str(_safe(lambda: device.serial) or "?"),
        kind=str(kind),
        main_port=getattr(main, "port", None) or None,
        display_port=getattr(display, "port", None) or None,
    )


def find_boards(freewili: Any | None = None) -> list[tuple[BoardInfo, Any]]:
    """All FREE-WILi boards on USB as ``(info, board)`` pairs."""
    if freewili is None:
        freewili, _ = import_freewili()
    try:
        boards = freewili.FreeWili.find_all()
    except Exception as exc:
        raise BoardUnavailableError(
            f"scanning USB for FREE-WILi boards failed: {exc}",
            "replug the board; if it persists, check `lsusb` lists it",
        ) from exc
    return [(board_info(board), board) for board in boards]


def _not_found_hint(boards: list[BoardInfo]) -> str:
    if any(info.kind.upper() == "UF2" for info in boards):
        return (
            "a board is in UF2 bootloader mode (it shows up as a USB drive, with no serial "
            "port). Power-cycle it, or flash firmware first."
        )
    return (
        "is it plugged in and switched on? Some USB cables are charge-only.\n"
        "`builderwars ports` lists every serial port this machine can see."
    )


def select_board(port: str | None, freewili: Any | None = None) -> tuple[BoardInfo, Any]:
    """Pick the board that owns ``port`` (either its main or display tty), or the first one."""
    found = find_boards(freewili)
    usable = [(info, board) for info, board in found if info.ports]
    if port is None:
        if not usable:
            raise BoardUnavailableError(
                "no FREE-WILi board found on USB", _not_found_hint([i for i, _ in found])
            )
        if len(usable) > 1:
            log.warning(
                "%d FREE-WILi boards found; using %s (pass a port to choose)",
                len(usable),
                usable[0][0].describe(),
            )
        return usable[0]
    for info, board in usable:
        if any(same_port(port, p) for p in info.ports):
            return info, board
    if usable:
        listing = "\n".join(f"  {info.describe()}" for info, _ in usable)
        raise BoardUnavailableError(
            f"{port} is not a FREE-WILi serial port",
            f"FREE-WILi boards found:\n{listing}\npass one of those ports instead",
        )
    raise BoardUnavailableError(
        f"{port} exists, but no FREE-WILi board was found on USB",
        "that port probably belongs to a different USB serial device.\n"
        + _not_found_hint([i for i, _ in found]),
    )


class FreeWiliSensors:
    """``SensorReader`` backed by a FREE-WILi attached to this host.

    ``port`` selects the board by its main or display tty (e.g. ``/dev/ttyACM0``); without it
    the first board found is used. ``device`` lets tests inject a fake.
    Reconnects lazily: if a read fails the device is dropped and re-discovered next time.
    """

    def __init__(
        self, device: Any | None = None, *, port: str | None = None, open_timeout_s: float = 6.0
    ) -> None:
        self._device = device
        self._injected = device is not None
        self.port = port
        self.open_timeout_s = float(open_timeout_s)
        self.info: BoardInfo | None = None
        self._buttons_ok = True

    @classmethod
    def adopt(cls, board: Any, info: BoardInfo, *, port: str | None = None) -> FreeWiliSensors:
        """Wrap a real board that is already open (e.g. after step-by-step checks)."""
        sensors = cls(port=port)
        sensors._device = board
        sensors.info = info
        return sensors

    def _processor(self, name: str) -> Any:
        if self._injected:
            return name
        _, processor_type = import_freewili()
        return getattr(processor_type, name)

    def connect(self) -> Any:
        """Find, check and open the board; raise ``BoardUnavailableError`` with a hint."""
        if self._device is not None:
            return self._device
        freewili, _ = import_freewili()
        if self.port is not None:
            self._check(self.port)
        info, board = select_board(self.port, freewili)
        for port in info.ports:  # the board opens both ttys; both need permissions
            self._check(port)
        opened: _Result = board.open(True, self.open_timeout_s)
        if opened.is_err():
            error = str(opened.unwrap_err())
            close_quietly(board)
            raise BoardUnavailableError(
                f"could not open {info.describe()}: {error}",
                open_error_hint(self.port or info.main_port, error),
            )
        self.info = info
        self._device = board
        return board

    @staticmethod
    def _check(port: str) -> None:
        try:
            check_port(port)
        except PortProblem as problem:
            raise BoardUnavailableError(problem.message, problem.hint) from None

    def read(self) -> dict[str, MetricValue]:
        device = self.connect()
        try:
            io: _Result = device.get_io(self._processor("Main"))
            if io.is_err():
                self._fail(f"reading GPIO from the main CPU failed: {io.unwrap_err()}")
            buttons: _Result | None = None
            if self._buttons_ok:
                buttons = device.read_all_buttons(self._processor("Display"))
                if buttons.is_err():
                    # The buttons are a nice-to-have: without the display CPU (some boards,
                    # or its port busy) keep sending the pins rather than going "degraded".
                    log.warning(
                        "reading buttons from the display CPU failed (%s); sending GPIO only",
                        buttons.unwrap_err(),
                    )
                    self._buttons_ok = False
                    buttons = None
        except BoardUnavailableError:
            raise
        except Exception as exc:  # serial errors surface as exceptions on unplug
            self.close()
            raise BoardUnavailableError(
                f"lost the FREE-WILi while reading ({type(exc).__name__}: {exc})",
                "was it unplugged or reset? It is reconnected automatically on the next read.",
            ) from exc

        readings: dict[str, MetricValue] = {
            f"io_{index}": int(level) for index, level in enumerate(io.unwrap())
        }
        for color, pressed in (buttons.unwrap() if buttons is not None else {}).items():
            name = getattr(color, "name", str(color)).lower()
            readings[f"button_{name}"] = bool(pressed)
        return readings

    def _fail(self, message: str) -> None:
        self.close()
        raise BoardUnavailableError(
            message, "the board answered with an error; replug it if this keeps happening"
        )

    def close(self) -> None:
        if self._device is not None and not self._injected:
            close_quietly(self._device)
            self._device = None


def close_quietly(board: Any) -> None:
    try:
        board.close()
    except Exception:  # pragma: no cover - best effort on a dead port
        log.debug("ignoring error while closing FREE-WILi", exc_info=True)
