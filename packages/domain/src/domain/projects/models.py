from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from domain.common import new_id, utcnow


class ProjectRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


@dataclass(frozen=True, slots=True)
class Project:
    """A workspace that groups devices, sessions, jobs and firmware for collaboration."""

    name: str
    owner_user_id: str
    id: str = field(default_factory=lambda: new_id("prj"))
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("project name must not be blank")


@dataclass(frozen=True, slots=True)
class ProjectMembership:
    project_id: str
    user_id: str
    role: ProjectRole
    created_at: datetime = field(default_factory=utcnow)
