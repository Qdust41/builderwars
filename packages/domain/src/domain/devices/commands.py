"""Cloud-side record of a command sent to a device (decision #5: role-based, no lock).

Commands from any authorised user queue per device (FIFO, bounded) and expire if the device
does not answer in time. Results arrive through the ingest path as ``command_result``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final
from uuid import uuid4

from domain.common import InvalidStateTransitionError, utcnow

MAX_PENDING_COMMANDS_PER_DEVICE: Final[int] = 32
DEFAULT_COMMAND_TTL: Final[timedelta] = timedelta(seconds=30)


class CommandStatus(StrEnum):
    QUEUED = "queued"  # accepted by the API, waiting for the dispatcher
    SENT = "sent"  # published to the device's commands topic
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"  # the device refused it (unknown, bad args, expired)
    TIMED_OUT = "timed_out"

    @property
    def is_pending(self) -> bool:
        return self in (CommandStatus.QUEUED, CommandStatus.SENT)


_RESULT_STATUSES: Final = frozenset(
    {CommandStatus.SUCCEEDED, CommandStatus.FAILED, CommandStatus.REJECTED}
)


@dataclass(frozen=True, slots=True)
class DeviceCommand:
    project_id: str
    device_id: str
    name: str
    requested_by: str
    args: dict[str, float | int | bool | str] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))  # == protocol command_id (UUID)
    status: CommandStatus = CommandStatus.QUEUED
    created_at: datetime = field(default_factory=utcnow)
    expires_at: datetime | None = None
    sent_at: datetime | None = None
    completed_at: datetime | None = None
    detail: str | None = None
    output: dict[str, float | int | bool | str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.expires_at is None:
            object.__setattr__(self, "expires_at", self.created_at + DEFAULT_COMMAND_TTL)

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at

    def mark_sent(self, now: datetime) -> DeviceCommand:
        if self.status is not CommandStatus.QUEUED:
            raise InvalidStateTransitionError(f"command {self.id} is {self.status.value}")
        return replace(self, status=CommandStatus.SENT, sent_at=now)

    def time_out(self, now: datetime) -> DeviceCommand:
        if not self.status.is_pending:
            raise InvalidStateTransitionError(f"command {self.id} is {self.status.value}")
        return replace(self, status=CommandStatus.TIMED_OUT, completed_at=now)

    def complete(
        self,
        status: CommandStatus,
        *,
        now: datetime,
        detail: str | None = None,
        output: dict[str, float | int | bool | str] | None = None,
    ) -> DeviceCommand:
        """Apply a device result. Idempotent: a repeat for a finished command is a no-op."""
        if status not in _RESULT_STATUSES:
            raise ValueError(f"{status.value} is not a result status")
        if not self.status.is_pending:
            return self
        return replace(
            self, status=status, completed_at=now, detail=detail, output=dict(output or {})
        )
