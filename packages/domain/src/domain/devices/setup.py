"""The test setup behind a device: laptop -> FREE-WILi -> up to 4 target boards, plus each
target board's sensors.

A ``Device`` is the registry entry. Its setup is kept in separate records (not on ``Device``)
because the ingest path rewrites the device row on every message (``last_seen_at``); keeping
the setup apart means a telemetry batch can never overwrite a sensor someone just added.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from domain.common import new_id, utcnow

# One FREE-WILi drives at most this many boards under test at once (owner decision 2026-11-15).
MAX_TARGET_BOARDS = 4


@dataclass(frozen=True, slots=True)
class TargetBoard:
    """A board under test wired to the device's FREE-WILi, as people describe it."""

    device_id: str
    name: str
    notes: str = ""
    id: str = field(default_factory=lambda: new_id("brd"))
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True, slots=True)
class DeviceSetup:
    """What the CLI last reported about the laptop (``host``) and the FREE-WILi (``bridge``):
    plain JSON objects validated by ``device_protocol.setup``."""

    device_id: str
    host: dict[str, Any] | None = None
    bridge: dict[str, Any] | None = None
    reported_at: datetime | None = None
    reported_by: str | None = None
    updated_at: datetime = field(default_factory=utcnow)

    def with_report(
        self,
        *,
        host: dict[str, Any],
        bridge: dict[str, Any] | None,
        by: str,
        at: datetime,
    ) -> DeviceSetup:
        return replace(
            self, host=host, bridge=bridge, reported_at=at, reported_by=by, updated_at=at
        )


@dataclass(frozen=True, slots=True)
class Sensor:
    """One value on a target board read through the FREE-WILi.

    ``key`` is the reading name in telemetry, unique per device (all of a device's boards
    share one telemetry stream). ``bus`` and ``decode`` are
    JSON objects validated by ``device_protocol.sensors.SensorSpec`` before they get here.
    """

    device_id: str
    board_id: str
    key: str
    name: str
    bus: dict[str, Any]
    decode: dict[str, Any]
    unit: str | None = None
    poll_interval_s: float = 1.0
    enabled: bool = True
    id: str = field(default_factory=lambda: new_id("sen"))
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    @property
    def protocol(self) -> str:
        return str(self.bus.get("protocol", ""))
