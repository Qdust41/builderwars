from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum

from domain.common import new_id, utcnow

# A device that has said nothing for this long counts as offline, even if its last message said
# online (the CLI was killed, the laptop slept, the network dropped). The host sends a
# heartbeat every 30 s and telemetry every few seconds while it runs.
STALE_AFTER = timedelta(seconds=75)


class ConnectionStatus(StrEnum):
    UNKNOWN = "unknown"  # registered but never heard from
    ONLINE = "online"
    OFFLINE = "offline"


@dataclass(frozen=True, slots=True)
class Device:
    """A registered device: one host PC + FREE-WILi board pair, one IoT thing (decision #2).

    Never put certificates or private keys on this model. Device credentials live in AWS IoT
    (and, for provisioning, a secrets store); this row only references the IoT thing name.
    """

    project_id: str
    display_name: str
    hardware_model: str  # e.g. "freewili-1-og"
    extensions: frozenset[str] = frozenset()  # e.g. {"bottlenose-wifi-orca"}
    id: str = field(default_factory=lambda: new_id("dev"))
    firmware_version: str | None = None
    connection_status: ConnectionStatus = ConnectionStatus.UNKNOWN
    last_seen_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)

    def status_at(self, now: datetime, *, stale_after: timedelta = STALE_AFTER) -> ConnectionStatus:
        """``connection_status``, except that a silent "online" device reads as offline."""
        if self.connection_status is ConnectionStatus.ONLINE and (
            self.last_seen_at is None or now - self.last_seen_at > stale_after
        ):
            return ConnectionStatus.OFFLINE
        return self.connection_status

    def observed(
        self,
        at: datetime,
        *,
        status: ConnectionStatus = ConnectionStatus.ONLINE,
        firmware_version: str | None = None,
    ) -> Device:
        """Return a copy updated from a device message.

        Messages can arrive out of order, so an older observation never moves ``last_seen_at``
        backwards or overrides a newer status.
        """
        if self.last_seen_at is not None and at < self.last_seen_at:
            return self
        return replace(
            self,
            last_seen_at=at,
            connection_status=status,
            firmware_version=firmware_version or self.firmware_version,
        )
