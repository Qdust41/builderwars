"""Read access to a device's recent telemetry and log stream (for the device dashboard)."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from application.ports import (
    DeviceLogEntry,
    DeviceLogRecord,
    DeviceRepository,
    LogPosition,
    TelemetryRepository,
    TelemetrySample,
)
from application.services.authorization import Authorizer
from domain.common import NotFoundError
from domain.devices import Device
from domain.projects import Permission

MAX_TELEMETRY_SAMPLES: Final[int] = 1000
MAX_LOG_ENTRIES: Final[int] = 500
#: Page size cap for the full-history log export (``GET /devices/{id}/logs/history``).
MAX_LOG_HISTORY_PAGE: Final[int] = 1000


class InvalidLogCursorError(ValueError):
    """The ``cursor`` was not produced by :func:`encode_log_cursor`."""


@dataclass(frozen=True, slots=True)
class LogHistoryPage:
    entries: list[DeviceLogRecord]
    #: Opaque; pass back as ``cursor`` for the next page. ``None`` when this was the last.
    next_cursor: str | None


def encode_log_cursor(position: LogPosition) -> str:
    raw = f"{position.at.isoformat()}|{position.source}|{position.row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_log_cursor(cursor: str) -> LogPosition:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        at, source, row_id = base64.urlsafe_b64decode(padded).decode().split("|")
        parsed = datetime.fromisoformat(at)
        if parsed.tzinfo is None:
            raise ValueError("naive timestamp")
        return LogPosition(at=parsed, source=int(source), row_id=int(row_id))
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise InvalidLogCursorError("cursor is not one this API returned") from exc


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

    def log_history(
        self,
        *,
        user_id: str,
        device_id: str,
        since: datetime | None = None,
        until: datetime | None = None,
        cursor: str | None = None,
        limit: int = MAX_LOG_HISTORY_PAGE,
    ) -> LogHistoryPage:
        """A device's whole log/event history, oldest first, one page at a time."""
        self._visible_device(user_id, device_id)
        since, until = _aware(since), _aware(until)  # a bare timestamp means UTC
        limit = max(1, min(limit, MAX_LOG_HISTORY_PAGE))
        after = decode_log_cursor(cursor) if cursor else None
        # Fetch one extra row to learn whether another page exists.
        rows = self._telemetry.log_history(
            device_id, since=since, until=until, after=after, limit=limit + 1
        )
        if len(rows) > limit:
            rows = rows[:limit]
            return LogHistoryPage(rows, encode_log_cursor(rows[-1].position))
        return LogHistoryPage(rows, None)

    def _visible_device(self, user_id: str, device_id: str) -> Device:
        device = self._devices.get(device_id)
        if device is None:
            raise NotFoundError("device", device_id)
        try:
            self._authorizer.require(user_id, device.project_id, Permission.VIEW_PROJECT)
        except NotFoundError:
            raise NotFoundError("device", device_id) from None
        return device


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
