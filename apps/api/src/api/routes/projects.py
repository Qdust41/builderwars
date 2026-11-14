from __future__ import annotations

from fastapi import APIRouter, status

from api.dependencies import ProjectServiceDep, UserDep
from api.schemas import ProjectCreate, ProjectOut

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
