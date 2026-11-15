"""The ``logger_real`` way of reading a FREE-WILi (``builderwars run --logger real``).

Ported from ``scripts/wili_code/src/logger_real.py``. Instead of the ``freewili`` package's
``get_io`` (which times out on some boards), it uses the vendor's newer ``onewili`` bindings
(github.com/freewili/onewili, not on PyPI) on the main CPU's serial port only:

* the whole GPIO bitfield in one ``i\\g\\u`` call (``gpio.read_all()``), and
* 14 bytes from an MPU6050 IMU at I2C 0x68, register 0x3B (accel x/y/z, temperature,
  gyro x/y/z as big-endian signed 16-bit counts).

Each sample goes to the dashboard as readings and, like the script, one row of the same CSV
(``LOGGER_CSV_COLUMNS``), so the file is interchangeable with the script's
``combined_gpio_imu.csv`` and ``builderwars upload`` accepts both.
"""

from __future__ import annotations

import csv
import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from board_runtime.hardware.sensors import BoardUnavailableError
from device_protocol.schemas import MetricValue

log = logging.getLogger(__name__)
app_log = logging.getLogger("board_runtime.app")  # forwarded to the dashboard's log

ONEWILI_INSTALL_HINT = (
    "onewili is not on PyPI; install it from the vendor's repository:\n"
    '  pip install "onewili @ git+https://github.com/freewili/onewili#subdirectory=python"'
)

I2C_ADDRESS = 0x68  # MPU6050 with AD0 low
MPU6050_PWR_MGMT_1 = 0x6B
IMU_REGISTER = 0x3B  # ACCEL_XOUT_H; 14 bytes run through GYRO_ZOUT_L
IMU_LENGTH = 14
GPIO_PINS = 32
IMU_VALUES = (
    "accel_x_raw",
    "accel_y_raw",
    "accel_z_raw",
    "temperature_raw",
    "gyro_x_raw",
    "gyro_y_raw",
    "gyro_z_raw",
)

# Exactly the script's header, in its order.
LOGGER_CSV_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "elapsed_s",
    "gpio_raw",
    "gpio_error",
    *(f"GPIO{i}" for i in range(GPIO_PINS)),
    "imu_raw_hex",
    "imu_error",
    *(f"imu_byte_{i}" for i in range(IMU_LENGTH)),
    *IMU_VALUES,
)

# Errors in a row (GPIO and IMU both failing) before the port is closed and opened again.
REOPEN_AFTER_FAILURES = 3


class OneWiliNotInstalledError(RuntimeError):
    """The vendor ``onewili`` package is missing. Fatal: not a transient board problem."""

    def __init__(self) -> None:
        super().__init__("the 'onewili' Python package is not installed")
        self.hint = ONEWILI_INSTALL_HINT


def import_onewili() -> Any:
    try:
        import onewili  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - host-only dependency
        raise OneWiliNotInstalledError() from exc
    return onewili


def _ok_value(result: Any) -> Any:
    """``Ok(value).ok_value`` from the ``result`` package; None for ``Err`` or odd objects."""
    try:
        if getattr(result, "is_err", lambda: False)():
            return None
        return result.ok_value
    except Exception:
        return None


def mpu6050_temp_c(raw: int) -> float:
    """MPU6050 datasheet: Temperature in degrees C = TEMP_OUT / 340 + 36.53."""
    return round(raw / 340.0 + 36.53, 2)


def decode_imu(data: bytes) -> list[int] | None:
    """The 7 signed 16-bit big-endian values, or None if the reply is short."""
    if len(data) != IMU_LENGTH:
        return None
    return [
        int.from_bytes(data[i : i + 2], byteorder="big", signed=True)
        for i in range(0, IMU_LENGTH, 2)
    ]


@dataclass(frozen=True)
class LoggerSample:
    """One read: what the script writes as one CSV row."""

    timestamp: datetime  # local, naive, as the script writes it
    elapsed_s: float
    gpio_raw: int | None
    gpio_error: str
    imu_data: bytes | None
    imu_error: str

    @property
    def imu_values(self) -> list[int] | None:
        return decode_imu(self.imu_data) if self.imu_data is not None else None

    def csv_row(self) -> list[Any]:
        if self.gpio_raw is not None:
            bits: list[Any] = [(self.gpio_raw >> bit) & 1 for bit in range(GPIO_PINS)]
        else:
            bits = [""] * GPIO_PINS
        imu_bytes: list[Any] = list(self.imu_data or b"")[:IMU_LENGTH]
        imu_bytes += [""] * (IMU_LENGTH - len(imu_bytes))
        values: list[Any] = self.imu_values or [""] * len(IMU_VALUES)
        return [
            self.timestamp.isoformat(),
            round(self.elapsed_s, 6),
            "" if self.gpio_raw is None else self.gpio_raw,
            self.gpio_error,
            *bits,
            self.imu_data.hex() if self.imu_data is not None else "",
            self.imu_error,
            *imu_bytes,
            *values,
        ]

    def readings(self) -> dict[str, MetricValue]:
        return readings_from(self.gpio_raw, self.imu_values)


def readings_from(gpio_raw: int | None, imu_values: Sequence[int] | None) -> dict[str, MetricValue]:
    """Dashboard readings for one sample: the bitfield, one 0/1 per pin, and the IMU."""
    readings: dict[str, MetricValue] = {}
    if gpio_raw is not None:
        readings["gpio_raw"] = gpio_raw
        for bit in range(GPIO_PINS):
            readings[f"gpio_{bit}"] = (gpio_raw >> bit) & 1
    if imu_values is not None:
        readings.update(zip(IMU_VALUES, imu_values, strict=True))
        readings["imu_temp_c"] = mpu6050_temp_c(imu_values[3])
    return readings


def readings_from_csv_row(row: dict[str, str]) -> dict[str, MetricValue]:
    """Readings for one row of a ``logger_real`` CSV (the script's or ours)."""
    gpio_raw = int(row["gpio_raw"]) if (row.get("gpio_raw") or "").strip() else None
    imu_values: list[int] | None = None
    if not (row.get("imu_error") or "").strip() and all(
        (row.get(name) or "").strip() for name in IMU_VALUES
    ):
        imu_values = [int(row[name]) for name in IMU_VALUES]
    return readings_from(gpio_raw, imu_values)


def is_logger_csv(fieldnames: Iterable[str] | None) -> bool:
    return tuple(fieldnames or ()) == LOGGER_CSV_COLUMNS


class LoggerCsv:
    """Appends samples to a CSV with the script's header; flushed every row like the script."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: IO[str] | None = None
        self._writer: Any = None

    def write(self, sample: LoggerSample) -> None:
        if self._writer is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open("w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._file)
            self._writer.writerow(LOGGER_CSV_COLUMNS)
        self._writer.writerow(sample.csv_row())
        assert self._file is not None
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
            self._writer = None


class LoggerRealSensors:
    """``SensorReader`` that reads a FREE-WILi the way ``logger_real.py`` does.

    ``port`` is the FREE-WILi's main serial port; without it the one board ``onewili`` finds
    is used. ``device`` lets tests inject a fake ``OneWili``. ``csv_path`` also writes the
    script's CSV. Like ``FreeWiliSensors``, it reconnects after repeated failures.
    """

    def __init__(
        self,
        device: Any | None = None,
        *,
        port: str | None = None,
        csv_path: Path | None = None,
        i2c_address: int = I2C_ADDRESS,
        clock: Any = time.monotonic,
    ) -> None:
        self._device = device
        self._injected = device is not None
        self._setup_done = False
        self.port = port
        self.i2c_address = i2c_address
        self.csv = LoggerCsv(csv_path) if csv_path is not None else None
        self._clock = clock
        self._start: float | None = None
        self._failures = 0
        self._gpio_failing = False
        self._imu_failing = False
        self.samples = 0
        self.main_port: str | None = port

    # -- connection ---------------------------------------------------------------------------

    def connect(self) -> Any:
        """Open the board and put the MPU6050 into a readable state."""
        if self._device is None:
            onewili = import_onewili()
            try:
                if self.port:
                    self._device = onewili.OneWili(self.port).open()
                else:
                    self._device = onewili.connect()
                    transport = getattr(self._device, "_transport", None)
                    self.main_port = getattr(transport, "port_name", None) or getattr(
                        transport, "port", None
                    )
            except Exception as exc:
                self._device = None
                raise BoardUnavailableError(
                    f"could not open the FREE-WILi with onewili: {exc}",
                    "is it plugged in, and not held by another program (`builderwars ports`)? "
                    "With several boards attached, pass the main port, e.g. /dev/ttyACM0",
                ) from exc
            self._setup_done = False
        if not self._setup_done:
            self._setup(self._device)
        return self._device

    def _setup(self, device: Any) -> None:
        i2c = device.io.i2c
        # FREE-WILi must be the I2C master, then wake the MPU6050 (PWR_MGMT_1 = 0).
        slave = i2c.i2c_slave_enable(0)
        wake = i2c.i2c_write(self.i2c_address, MPU6050_PWR_MGMT_1, bytes([0x00]))
        for what, result in (("disable I2C slave mode", slave), ("wake the MPU6050", wake)):
            if getattr(result, "is_err", lambda: False)():
                app_log.warning("logger: could not %s: %s", what, result)
        self._setup_done = True

    def close(self) -> None:
        if self._device is not None and not self._injected:
            try:
                self._device.close()
            except Exception:
                log.debug("ignoring error while closing onewili", exc_info=True)
            self._device = None
        if self.csv is not None:
            self.csv.close()

    # -- reading ------------------------------------------------------------------------------

    def _read_gpio(self, device: Any) -> tuple[int | None, str]:
        result = device.io.gpio.read_all()
        value = _ok_value(result)
        if value is None:
            return None, str(result)
        return int(value), ""

    def _read_imu(self, device: Any) -> tuple[bytes | None, str]:
        # The script calls the firmware's i\i\r with address/register/length directly: the
        # generated i2c_read() takes no arguments.
        result = device.io.i2c._call(
            "r",
            [f"{self.i2c_address:02X}", f"{IMU_REGISTER:02X}", str(IMU_LENGTH)],
            ["bytes"],
            timeout=3.0,
        )
        value = _ok_value(result)
        if value is None:
            return None, str(result)
        data = bytes(value)
        error = "" if len(data) == IMU_LENGTH else f"Unexpected length: {len(data)}"
        return data, error

    def sample(self) -> LoggerSample:
        device = self.connect()
        now = self._clock()
        if self._start is None:
            self._start = now
        try:
            gpio_raw, gpio_error = self._read_gpio(device)
            imu_data, imu_error = self._read_imu(device)
        except Exception as exc:  # serial errors surface as exceptions on unplug
            self._drop()
            raise BoardUnavailableError(
                f"lost the FREE-WILi while reading ({type(exc).__name__}: {exc})",
                "was it unplugged or reset? It is reconnected automatically on the next read.",
            ) from exc
        return LoggerSample(
            timestamp=datetime.now(),
            elapsed_s=now - self._start,
            gpio_raw=gpio_raw,
            gpio_error=gpio_error,
            imu_data=imu_data,
            imu_error=imu_error,
        )

    def read(self) -> dict[str, MetricValue]:
        sample = self.sample()
        if self.csv is not None:
            self.csv.write(sample)  # failed reads too, with their error, as the script does
        self.samples += 1
        self._gpio_failing = self._note("GPIO", sample.gpio_error, self._gpio_failing)
        imu_problem = sample.imu_error if sample.imu_values is None else ""
        self._imu_failing = self._note("IMU (I2C)", imu_problem, self._imu_failing)
        readings = sample.readings()
        if not readings:
            self._failures += 1
            if self._failures >= REOPEN_AFTER_FAILURES:
                self._failures = 0
                self._drop()
            raise BoardUnavailableError(
                f"the FREE-WILi answered neither GPIO nor I2C reads: {sample.gpio_error}",
                "check `builderwars ports`, replug the FREE-WILi, and that the MPU6050 is "
                "wired to the I2C header (SDA 16 / SCL 17)",
            )
        self._failures = 0
        return readings

    def _note(self, what: str, error: str, was_failing: bool) -> bool:
        """Log a failing read once when it starts and once when it recovers, not every sample."""
        if error and not was_failing:
            app_log.warning("logger: reading %s failed, sending the rest: %s", what, error)
        elif not error and was_failing:
            app_log.info("logger: reading %s works again", what)
        return bool(error)

    def _drop(self) -> None:
        if self._device is not None and not self._injected:
            try:
                self._device.close()
            except Exception:
                log.debug("ignoring error while closing onewili", exc_info=True)
            self._device = None
        self._setup_done = False
