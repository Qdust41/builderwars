from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from domain.common import InvalidStateTransitionError, new_id, utcnow


class SessionStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"


@dataclass(frozen=True, slots=True)
class Session:
    """A realtime collaboration context for a project, optionally focused on one device.

    What "multiplayer" means (shared viewing/control vs. simultaneous editing) and how device
    control is locked between users are open decisions (docs/open-decisions.md #4, #5).
    """

    project_id: str
    created_by: str
    device_id: str | None = None
    id: str = field(default_factory=lambda: new_id("ses"))
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = field(default_factory=utcnow)

    def end(self) -> Session:
        if self.status is SessionStatus.ENDED:
            raise InvalidStateTransitionError(f"session {self.id} already ended")
        return replace(self, status=SessionStatus.ENDED)
