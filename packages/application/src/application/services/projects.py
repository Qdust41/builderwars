from __future__ import annotations

from dataclasses import dataclass

from application.ports import MembershipRepository, ProjectRepository, UserDirectory
from application.services.authorization import Authorizer
from domain.common import ConflictError, NotFoundError, PermissionDeniedError
from domain.projects import Permission, Project, ProjectMembership, ProjectRole

# Roles an owner/admin can hand out. Ownership is never granted through membership changes.
GRANTABLE_ROLES = frozenset({ProjectRole.ADMIN, ProjectRole.MEMBER, ProjectRole.VIEWER})


@dataclass(frozen=True, slots=True)
class ProjectMember:
    membership: ProjectMembership
    email: str | None  # None when the account no longer exists in the directory


class ProjectService:
    def __init__(
        self,
        projects: ProjectRepository,
        memberships: MembershipRepository,
        authorizer: Authorizer,
        users: UserDirectory,
    ) -> None:
        self._projects = projects
        self._memberships = memberships
        self._authorizer = authorizer
        self._users = users

    def create_project(self, *, user_id: str, name: str) -> Project:
        # TODO: wrap in a unit of work once a transactional repository exists.
        project = Project(name=name.strip(), owner_user_id=user_id)
        self._projects.add(project)
        self._memberships.add(
            ProjectMembership(project_id=project.id, user_id=user_id, role=ProjectRole.OWNER)
        )
        return project

    def list_projects(self, *, user_id: str) -> list[Project]:
        ids = [m.project_id for m in self._memberships.list_for_user(user_id)]
        return self._projects.list_by_ids(ids)

    def get_project(self, *, user_id: str, project_id: str) -> Project:
        self._authorizer.require(user_id, project_id, Permission.VIEW_PROJECT)
        project = self._projects.get(project_id)
        if project is None:  # membership exists but project vanished: treat as not found
            raise NotFoundError("project", project_id)
        return project

    # --- Members (decision #10: owner/admin add people by email; no invite links, no orgs) ---

    def list_members(self, *, user_id: str, project_id: str) -> list[ProjectMember]:
        self._authorizer.require(user_id, project_id, Permission.VIEW_PROJECT)
        members = []
        for m in sorted(self._memberships.list_for_project(project_id), key=_member_order):
            user = self._users.get(m.user_id)
            members.append(ProjectMember(m, user.email if user else None))
        return members

    def add_member(
        self, *, user_id: str, project_id: str, email: str, role: ProjectRole
    ) -> ProjectMember:
        """Add an existing account to the project. Only an owner may grant ``admin``."""
        actor_role = self._authorizer.require(user_id, project_id, Permission.MANAGE_MEMBERS)
        if role not in GRANTABLE_ROLES:
            raise PermissionDeniedError(f"role {role.value!r} cannot be granted")
        if role is ProjectRole.ADMIN and actor_role is not ProjectRole.OWNER:
            raise PermissionDeniedError("only the project owner can add admins")
        user = self._users.find_by_email(email)
        if user is None:
            # Accounts are created outside the app while self sign-up is off (decision #10).
            raise NotFoundError("user", email)
        if self._memberships.get(project_id, user.user_id) is not None:
            raise ConflictError(f"{email!r} is already a member of project {project_id}")
        membership = ProjectMembership(project_id=project_id, user_id=user.user_id, role=role)
        self._memberships.add(membership)
        return ProjectMember(membership, user.email)

    def remove_member(self, *, user_id: str, project_id: str, member_user_id: str) -> None:
        """Remove a member. Anyone but the owner may leave; only the owner may remove admins."""
        if member_user_id == user_id:
            actor_role = self._authorizer.require(user_id, project_id, Permission.VIEW_PROJECT)
            if actor_role is ProjectRole.OWNER:
                raise PermissionDeniedError("the project owner cannot leave the project")
            self._memberships.remove(project_id, member_user_id)
            return
        actor_role = self._authorizer.require(user_id, project_id, Permission.MANAGE_MEMBERS)
        target = self._memberships.get(project_id, member_user_id)
        if target is None:
            raise NotFoundError("member", member_user_id)
        if target.role is ProjectRole.OWNER:
            raise PermissionDeniedError("the project owner cannot be removed")
        if target.role is ProjectRole.ADMIN and actor_role is not ProjectRole.OWNER:
            raise PermissionDeniedError("only the project owner can remove admins")
        self._memberships.remove(project_id, member_user_id)

    # TODO: change a member's role, transfer ownership, rename, archive.


_ROLE_ORDER = {
    ProjectRole.OWNER: 0,
    ProjectRole.ADMIN: 1,
    ProjectRole.MEMBER: 2,
    ProjectRole.VIEWER: 3,
}


def _member_order(m: ProjectMembership) -> tuple[int, object]:
    return (_ROLE_ORDER[m.role], m.created_at)
