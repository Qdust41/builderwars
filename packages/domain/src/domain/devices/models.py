from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from domain.common import new_id, utcnow


class ConnectionStatus(StrEnum):
    UNKNOWN = "unknown"  # registered but never heard from
    ONLINE = "online"
    OFFLINE = "offline"


@dataclass(frozen=True, slots=True)
class Device:
    """A registered physical board.

    Never put certificates or private keys on this model. Device credentials live in AWS IoT
    (and, for provisioning, a secrets store); this row only references the IoT thing name.
    """

    project_id: str
    display_name: str
    hardware_model: str
    id: str = field(default_factory=lambda: new_id("dev"))
    firmware_version: str | None = None
    connection_status: ConnectionStatus = ConnectionStatus.UNKNOWN
    last_seen_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)

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
