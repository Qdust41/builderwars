"""Host runtime configuration, read from the environment. Credentials are never hard-coded.

Certificates/keys are referenced by file path only; this module never reads their contents.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from device_protocol.compat import StrEnum
from device_protocol.schemas import TELEMETRY_BATCH_WINDOW_S, TELEMETRY_MAX_SAMPLES


class TransportKind(StrEnum):
    STDOUT = "stdout"  # local development: print JSON lines
    MQTT = "mqtt"  # AWS IoT Core over MQTT/TLS (awsiotsdk, optional extra "mqtt")


class SensorKind(StrEnum):
    SIMULATED = "simulated"
    FREEWILI = "freewili"  # real FREE-WILi over USB serial (optional extra "freewili")


class ConfigError(ValueError):
    pass


def default_state_dir() -> Path:
    return Path.home() / ".builderwars"


def log_csv_path_from_env(e: dict[str, str]) -> Path | None:
    """Resolve ``BUILDERWARS_LOG_CSV``: unset -> default under the state dir; off -> None."""
    raw = e.get("BUILDERWARS_LOG_CSV")
    if raw is None:
        state_dir = (
            Path(e["BUILDERWARS_STATE_DIR"]).expanduser()
            if e.get("BUILDERWARS_STATE_DIR")
            else default_state_dir()
        )
        device_id = e.get("DEVICE_ID", "device")
        return state_dir / "logs" / f"{device_id}.csv"
    if raw.strip().lower() in {"", "0", "off", "none", "false"}:
        return None
    return Path(raw).expanduser()


def _enum(e: dict[str, str], name: str, enum_cls: type[StrEnum], default: str) -> Any:
    raw = e.get(name) or default
    try:
        return enum_cls(raw.strip().lower())
    except ValueError:
        choices = ", ".join(member.value for member in enum_cls)
        raise ConfigError(f"{name}={raw!r} is not valid; use one of: {choices}") from None


def _number(e: dict[str, str], name: str, default: str, kind: type = float) -> Any:
    raw = e.get(name) or default
    try:
        return kind(raw)
    except ValueError:
        what = "a whole number" if kind is int else "a number"
        raise ConfigError(f"{name}={raw!r} is not {what}") from None


@dataclass(frozen=True)
class DeviceConfig:
    device_id: str
    hardware_model: str
    firmware_version: str
    transport: TransportKind
    sensors: SensorKind = SensorKind.SIMULATED
    sample_interval_s: float = 1.0
    batch_window_s: float = TELEMETRY_BATCH_WINDOW_S
    batch_max_samples: int = TELEMETRY_MAX_SAMPLES
    heartbeat_interval_s: float = 30.0
    state_dir: Path | None = None  # None -> sequence numbers are not persisted (tests/sim)
    mqtt_endpoint: str | None = None
    mqtt_port: int = 8883
    cert_path: Path | None = None
    key_path: Path | None = None
    ca_path: Path | None = None
    offline_buffer_size: int = 1000
    log_csv_path: Path | None = None  # None -> no local CSV log sink (see from_env)
    serial_port: str | None = None  # FREE-WILi tty (main or display); None -> first board found

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> DeviceConfig:
        e = dict(os.environ if env is None else env)
        device_id = (e.get("DEVICE_ID") or "").strip()
        if not device_id:
            raise ConfigError(
                "DEVICE_ID is not set; export it (e.g. DEVICE_ID=dev-local-001) or pass --device-id"
            )
        serial_port = (e.get("DEVICE_PORT") or "").strip() or None
        # A port only makes sense for real hardware, so it implies DEVICE_SENSORS=freewili.
        default_sensors = SensorKind.FREEWILI if serial_port else SensorKind.SIMULATED
        cfg = cls(
            device_id=device_id,
            hardware_model=e.get("DEVICE_HARDWARE_MODEL", "freewili-1-og"),
            firmware_version=e.get("DEVICE_FIRMWARE_VERSION", "0.0.0-dev"),
            transport=_enum(e, "DEVICE_TRANSPORT", TransportKind, TransportKind.STDOUT),
            sensors=_enum(e, "DEVICE_SENSORS", SensorKind, default_sensors),
            serial_port=serial_port,
            sample_interval_s=_number(e, "DEVICE_SAMPLE_INTERVAL_S", "1"),
            batch_window_s=_number(e, "DEVICE_BATCH_WINDOW_S", str(TELEMETRY_BATCH_WINDOW_S)),
            heartbeat_interval_s=_number(e, "DEVICE_HEARTBEAT_INTERVAL_S", "30"),
            state_dir=Path(e["BUILDERWARS_STATE_DIR"]).expanduser()
            if e.get("BUILDERWARS_STATE_DIR")
            else default_state_dir(),
            log_csv_path=log_csv_path_from_env(e),
            mqtt_endpoint=e.get("IOT_ENDPOINT") or None,
            mqtt_port=_number(e, "IOT_PORT", "8883", int),
            cert_path=Path(e["IOT_CERT_PATH"]).expanduser() if e.get("IOT_CERT_PATH") else None,
            key_path=Path(e["IOT_KEY_PATH"]).expanduser() if e.get("IOT_KEY_PATH") else None,
            ca_path=Path(e["IOT_CA_PATH"]).expanduser() if e.get("IOT_CA_PATH") else None,
        )
        cfg.validate()
        if cfg.transport is TransportKind.MQTT:
            for name, path in {
                "IOT_CERT_PATH": cfg.cert_path,
                "IOT_KEY_PATH": cfg.key_path,
                "IOT_CA_PATH": cfg.ca_path,
            }.items():
                if path is not None and not path.is_file():
                    raise ConfigError(f"{name} points to {path}, which does not exist")
        return cfg

    def validate(self) -> None:
        if not 1 <= self.batch_max_samples <= TELEMETRY_MAX_SAMPLES:
            raise ConfigError(f"batch_max_samples must be 1..{TELEMETRY_MAX_SAMPLES}")
        if self.batch_window_s <= 0 or self.sample_interval_s <= 0:
            raise ConfigError(
                "DEVICE_SAMPLE_INTERVAL_S and DEVICE_BATCH_WINDOW_S must be greater than 0"
            )
        if self.transport is TransportKind.MQTT:
            missing = [
                name
                for name, value in {
                    "IOT_ENDPOINT": self.mqtt_endpoint,
                    "IOT_CERT_PATH": self.cert_path,
                    "IOT_KEY_PATH": self.key_path,
                    "IOT_CA_PATH": self.ca_path,
                }.items()
                if not value
            ]
            if missing:
                raise ConfigError(
                    f"DEVICE_TRANSPORT=mqtt also needs {', '.join(missing)} to be set "
                    "(see device/README.md)"
                )
