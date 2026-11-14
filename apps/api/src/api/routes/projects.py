from __future__ import annotations

from fastapi import APIRouter, Response, status

from api.dependencies import ProjectServiceDep, UserDep
from api.schemas import MemberAdd, MemberOut, ProjectCreate, ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(user: UserDep, service: ProjectServiceDep) -> list[ProjectOut]:
    return [ProjectOut.of(p) for p in service.list_projects(user_id=user.user_id)]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, user: UserDep, service: ProjectServiceDep) -> ProjectOut:
    return ProjectOut.of(service.create_project(user_id=user.user_id, name=body.name))


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, user: UserDep, service: ProjectServiceDep) -> ProjectOut:
    return ProjectOut.of(service.get_project(user_id=user.user_id, project_id=project_id))


@router.get("/{project_id}/members", response_model=list[MemberOut])
def list_members(project_id: str, user: UserDep, service: ProjectServiceDep) -> list[MemberOut]:
    members = service.list_members(user_id=user.user_id, project_id=project_id)
    return [MemberOut.of(m) for m in members]


@router.post("/{project_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(
    project_id: str, body: MemberAdd, user: UserDep, service: ProjectServiceDep
) -> MemberOut:
    member = service.add_member(
        user_id=user.user_id, project_id=project_id, email=body.email, role=body.role
    )
    return MemberOut.of(member)


@router.delete("/{project_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    project_id: str, member_user_id: str, user: UserDep, service: ProjectServiceDep
) -> Response:
    service.remove_member(
        user_id=user.user_id, project_id=project_id, member_user_id=member_user_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
