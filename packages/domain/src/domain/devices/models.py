from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from domain.common import InvalidStateTransitionError, new_id, utcnow


class ConnectionStatus(StrEnum):
    UNKNOWN = "unknown"  # registered but never heard from
    ONLINE = "online"
    OFFLINE = "offline"


class DeviceLifecycle(StrEnum):
    """Whether the device may talk to the cloud at all (spec 03)."""

    ACTIVE = "active"
    REVOKED = "revoked"  # certificate revoked; its messages are quarantined; history is kept


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
    lifecycle: DeviceLifecycle = DeviceLifecycle.ACTIVE
    revoked_at: datetime | None = None

    @property
    def is_revoked(self) -> bool:
        return self.lifecycle is DeviceLifecycle.REVOKED

    def revoke(self, at: datetime) -> Device:
        """Return a revoked copy. Idempotent, so a retried revoke keeps the first timestamp."""
        if self.is_revoked:
            return self
        return replace(
            self,
            lifecycle=DeviceLifecycle.REVOKED,
            revoked_at=at,
            connection_status=ConnectionStatus.OFFLINE,
        )

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
        if self.is_revoked:
            raise InvalidStateTransitionError(f"device {self.id} is revoked")
        if self.last_seen_at is not None and at < self.last_seen_at:
            return self
        return replace(
            self,
            last_seen_at=at,
            connection_status=status,
            firmware_version=firmware_version or self.firmware_version,
        )
