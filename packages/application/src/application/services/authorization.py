from __future__ import annotations

from application.ports import MembershipRepository
from domain.common import NotFoundError, PermissionDeniedError
from domain.projects import Permission, ProjectRole, role_allows


class Authorizer:
    """Project-membership authorisation used by every project-scoped operation."""

    def __init__(self, memberships: MembershipRepository) -> None:
        self._memberships = memberships

    def role_of(self, user_id: str, project_id: str) -> ProjectRole | None:
        membership = self._memberships.get(project_id, user_id)
        return membership.role if membership else None

    def require(self, user_id: str, project_id: str, permission: Permission) -> ProjectRole:
        role = self.role_of(user_id, project_id)
        if role is None:
            # Non-members get "not found" so project ids cannot be probed.
            raise NotFoundError("project", project_id)
        if not role_allows(role, permission):
            raise PermissionDeniedError(
                f"role {role.value!r} lacks {permission.value!r} on project {project_id}"
            )
        return role
