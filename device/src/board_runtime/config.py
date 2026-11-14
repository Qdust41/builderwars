"""Host runtime configuration, read from the environment. Credentials are never hard-coded.

Certificates/keys are referenced by file path only; this module never reads their contents.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from device_protocol.compat import StrEnum
from device_protocol.schemas import TELEMETRY_BATCH_WINDOW_S, TELEMETRY_MAX_SAMPLES


class TransportKind(StrEnum):
    STDOUT = "stdout"  # local development: print JSON lines
    MQTT = "mqtt"  # AWS IoT Core over MQTT/TLS (awsiotsdk, optional extra "mqtt")
    LOCAL_API = "local-api"  # local development: talk to a local API's /local routes


class SensorKind(StrEnum):
    SIMULATED = "simulated"
    FREEWILI = "freewili"  # real FREE-WILi over USB serial (optional extra "freewili")


class ConfigError(ValueError):
    pass


def default_state_dir() -> Path:
    return Path.home() / ".builderwars"


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
    local_api_url: str = "http://localhost:8000"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> DeviceConfig:
        e = dict(os.environ if env is None else env)
        try:
            device_id = e["DEVICE_ID"]
        except KeyError:
            raise ConfigError("DEVICE_ID is required") from None
        cfg = cls(
            device_id=device_id,
            hardware_model=e.get("DEVICE_HARDWARE_MODEL", "freewili-1-og"),
            firmware_version=e.get("DEVICE_FIRMWARE_VERSION", "0.0.0-dev"),
            transport=TransportKind(e.get("DEVICE_TRANSPORT", TransportKind.STDOUT)),
            sensors=SensorKind(e.get("DEVICE_SENSORS", SensorKind.SIMULATED)),
            sample_interval_s=float(e.get("DEVICE_SAMPLE_INTERVAL_S", "1")),
            batch_window_s=float(e.get("DEVICE_BATCH_WINDOW_S", str(TELEMETRY_BATCH_WINDOW_S))),
            heartbeat_interval_s=float(e.get("DEVICE_HEARTBEAT_INTERVAL_S", "30")),
            state_dir=Path(e["BUILDERWARS_STATE_DIR"]).expanduser()
            if e.get("BUILDERWARS_STATE_DIR")
            else default_state_dir(),
            mqtt_endpoint=e.get("IOT_ENDPOINT") or None,
            mqtt_port=int(e.get("IOT_PORT", "8883")),
            cert_path=Path(e["IOT_CERT_PATH"]).expanduser() if e.get("IOT_CERT_PATH") else None,
            key_path=Path(e["IOT_KEY_PATH"]).expanduser() if e.get("IOT_KEY_PATH") else None,
            ca_path=Path(e["IOT_CA_PATH"]).expanduser() if e.get("IOT_CA_PATH") else None,
            local_api_url=e.get("LOCAL_API_URL", "http://localhost:8000"),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not 1 <= self.batch_max_samples <= TELEMETRY_MAX_SAMPLES:
            raise ConfigError(f"batch_max_samples must be 1..{TELEMETRY_MAX_SAMPLES}")
        if self.batch_window_s <= 0 or self.sample_interval_s <= 0:
            raise ConfigError("intervals must be positive")
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
                raise ConfigError(f"MQTT transport requires {', '.join(missing)}")
