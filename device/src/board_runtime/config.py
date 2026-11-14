"""Device configuration, read from the environment. Credentials are never hard-coded.

Certificates/keys are referenced by file path only; this module never reads their contents.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class TransportKind(StrEnum):
    STDOUT = "stdout"  # local development: print JSON lines
    MQTT = "mqtt"  # AWS IoT Core over MQTT/TLS (stub, not implemented)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    device_id: str
    hardware_model: str
    firmware_version: str
    transport: TransportKind
    telemetry_interval_s: float = 5.0
    heartbeat_interval_s: float = 30.0
    mqtt_endpoint: str | None = None
    mqtt_port: int = 8883
    cert_path: Path | None = None
    key_path: Path | None = None
    ca_path: Path | None = None
    offline_buffer_size: int = 1000

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> DeviceConfig:
        e = dict(os.environ if env is None else env)
        try:
            device_id = e["DEVICE_ID"]
        except KeyError:
            raise ConfigError("DEVICE_ID is required") from None
        cfg = cls(
            device_id=device_id,
            hardware_model=e.get("DEVICE_HARDWARE_MODEL", "unknown"),
            firmware_version=e.get("DEVICE_FIRMWARE_VERSION", "0.0.0-dev"),
            transport=TransportKind(e.get("DEVICE_TRANSPORT", TransportKind.STDOUT)),
            telemetry_interval_s=float(e.get("DEVICE_TELEMETRY_INTERVAL_S", "5")),
            heartbeat_interval_s=float(e.get("DEVICE_HEARTBEAT_INTERVAL_S", "30")),
            mqtt_endpoint=e.get("IOT_ENDPOINT") or None,
            mqtt_port=int(e.get("IOT_PORT", "8883")),
            cert_path=Path(e["IOT_CERT_PATH"]) if e.get("IOT_CERT_PATH") else None,
            key_path=Path(e["IOT_KEY_PATH"]) if e.get("IOT_KEY_PATH") else None,
            ca_path=Path(e["IOT_CA_PATH"]) if e.get("IOT_CA_PATH") else None,
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
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
