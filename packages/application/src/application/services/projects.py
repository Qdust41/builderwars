from __future__ import annotations

from application.ports import MembershipRepository, ProjectRepository
from application.services.authorization import Authorizer
from domain.common import NotFoundError
from domain.projects import Permission, Project, ProjectMembership, ProjectRole


class ProjectService:
    def __init__(
        self,
        projects: ProjectRepository,
        memberships: MembershipRepository,
        authorizer: Authorizer,
    ) -> None:
        self._projects = projects
        self._memberships = memberships
        self._authorizer = authorizer

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

    # TODO: add/remove members, rename, archive. Sharing model is open decision #10.
