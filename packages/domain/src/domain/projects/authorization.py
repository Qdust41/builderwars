"""Role -> permission matrix for project-scoped actions.

The exact sharing model is an open product decision (docs/open-decisions.md #10). This matrix
is a conservative starting point: only owners/admins touch hardware-affecting actions.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from domain.projects.models import ProjectRole


class Permission(StrEnum):
    VIEW_PROJECT = "project:view"
    MANAGE_PROJECT = "project:manage"
    MANAGE_MEMBERS = "project:manage_members"
    REGISTER_DEVICE = "device:register"
    SEND_DEVICE_COMMAND = "device:command"
    JOIN_SESSION = "session:join"
    START_SESSION = "session:start"
    CREATE_JOB = "job:create"
    APPROVE_FIRMWARE = "firmware:approve"


_VIEWER: Final = frozenset({Permission.VIEW_PROJECT, Permission.JOIN_SESSION})
_MEMBER: Final = _VIEWER | {Permission.START_SESSION, Permission.CREATE_JOB}
_ADMIN: Final = _MEMBER | {
    Permission.MANAGE_PROJECT,
    Permission.MANAGE_MEMBERS,
    Permission.REGISTER_DEVICE,
    Permission.SEND_DEVICE_COMMAND,
    Permission.APPROVE_FIRMWARE,
}
_OWNER: Final = _ADMIN

ROLE_PERMISSIONS: Final[dict[ProjectRole, frozenset[Permission]]] = {
    ProjectRole.VIEWER: _VIEWER,
    ProjectRole.MEMBER: frozenset(_MEMBER),
    ProjectRole.ADMIN: frozenset(_ADMIN),
    ProjectRole.OWNER: frozenset(_OWNER),
}


def role_allows(role: ProjectRole | None, permission: Permission) -> bool:
    """``None`` means "not a member", which grants nothing."""
    return role is not None and permission in ROLE_PERMISSIONS[role]
