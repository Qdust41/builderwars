"""Read access to a device's recent telemetry and log stream (for the device dashboard)."""

from __future__ import annotations

from typing import Final

from application.ports import DeviceLogEntry, DeviceRepository, TelemetryRepository, TelemetrySample
from application.services.authorization import Authorizer
from domain.common import NotFoundError
from domain.devices import Device
from domain.projects import Permission

MAX_TELEMETRY_SAMPLES: Final[int] = 1000
MAX_LOG_ENTRIES: Final[int] = 500


class TelemetryQueryService:
    def __init__(
        self, devices: DeviceRepository, telemetry: TelemetryRepository, authorizer: Authorizer
    ) -> None:
        self._devices = devices
        self._telemetry = telemetry
        self._authorizer = authorizer

    def recent_telemetry(
        self, *, user_id: str, device_id: str, limit: int
    ) -> list[TelemetrySample]:
        self._visible_device(user_id, device_id)
        return self._telemetry.recent_telemetry(
            device_id, limit=max(0, min(limit, MAX_TELEMETRY_SAMPLES))
        )

    def recent_logs(self, *, user_id: str, device_id: str, limit: int) -> list[DeviceLogEntry]:
        self._visible_device(user_id, device_id)
        return self._telemetry.recent_logs(device_id, limit=max(0, min(limit, MAX_LOG_ENTRIES)))

    def _visible_device(self, user_id: str, device_id: str) -> Device:
        device = self._devices.get(device_id)
        if device is None:
            raise NotFoundError("device", device_id)
        try:
            self._authorizer.require(user_id, device.project_id, Permission.VIEW_PROJECT)
        except NotFoundError:
            raise NotFoundError("device", device_id) from None
        return device
