"""Dependency wiring. Routes depend on services via FastAPI ``Depends``; services depend on ports.

``build_container`` is the single place that chooses adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from api.settings import AuthMode, RepositoryBackend, Settings, validate_settings
from application.adapters import memory
from application.services import (
    Authorizer,
    DeviceService,
    JobService,
    ProjectService,
    SessionService,
)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: str


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    authorizer: Authorizer
    projects: ProjectService
    devices: DeviceService
    sessions: SessionService
    jobs: JobService


def build_container(settings: Settings) -> Container:
    validate_settings(settings)
    if settings.repository_backend is not RepositoryBackend.MEMORY:
        # TODO: PostgreSQL repositories, SQS job queue, AppSync realtime publisher.
        raise NotImplementedError(
            f"repository backend {settings.repository_backend.value!r} is not implemented yet"
        )

    projects = memory.InMemoryProjectRepository()
    memberships = memory.InMemoryMembershipRepository()
    devices = memory.InMemoryDeviceRepository()
    sessions = memory.InMemorySessionRepository()
    jobs = memory.InMemoryJobRepository()
    authorizer = Authorizer(memberships)
    return Container(
        settings=settings,
        authorizer=authorizer,
        projects=ProjectService(projects, memberships, authorizer),
        devices=DeviceService(devices, authorizer),
        sessions=SessionService(sessions, devices, authorizer, memory.RecordingRealtimePublisher()),
        jobs=JobService(jobs, devices, memory.InMemoryJobQueue(), authorizer),
    )


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_current_user(
    container: ContainerDep,
    x_dev_user: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    mode = container.settings.auth_mode
    if mode is AuthMode.DEV_HEADER:
        # LOCAL ONLY: validate_settings() forbids this mode outside local/test.
        if not x_dev_user:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing X-Dev-User header")
        return CurrentUser(user_id=x_dev_user)
    # TODO: verify the Cognito JWT (issuer, audience, expiry, signature via JWKS). Behind API
    # Gateway's JWT authorizer the claims arrive in the Lambda event; read them from there.
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Cognito authentication not implemented")


UserDep = Annotated[CurrentUser, Depends(get_current_user)]


def get_project_service(container: ContainerDep) -> ProjectService:
    return container.projects


def get_device_service(container: ContainerDep) -> DeviceService:
    return container.devices


def get_session_service(container: ContainerDep) -> SessionService:
    return container.sessions


def get_job_service(container: ContainerDep) -> JobService:
    return container.jobs


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
DeviceServiceDep = Annotated[DeviceService, Depends(get_device_service)]
SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
JobServiceDep = Annotated[JobService, Depends(get_job_service)]
