"""Dependency wiring. Routes depend on services via FastAPI ``Depends``; services depend on ports.

``build_container`` is the single place that chooses adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from psycopg_pool import ConnectionPool

from api.settings import (
    LOCAL_ONLY_ENVS,
    AuthMode,
    RepositoryBackend,
    Settings,
    validate_settings,
)
from application.adapters import memory, postgres
from application.ports.repositories import (
    DeviceCommandRepository,
    DeviceRepository,
    JobRepository,
    MembershipRepository,
    ProjectRepository,
    SessionRepository,
)
from application.services import (
    Authorizer,
    CommandService,
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
    commands: CommandService
    pool: ConnectionPool | None = None  # closed on app shutdown

    def close(self) -> None:
        if self.pool is not None:
            self.pool.close()


@dataclass(frozen=True, slots=True)
class _Repositories:
    projects: ProjectRepository
    memberships: MembershipRepository
    devices: DeviceRepository
    sessions: SessionRepository
    jobs: JobRepository
    commands: DeviceCommandRepository


def _memory_repositories() -> _Repositories:
    return _Repositories(
        projects=memory.InMemoryProjectRepository(),
        memberships=memory.InMemoryMembershipRepository(),
        devices=memory.InMemoryDeviceRepository(),
        sessions=memory.InMemorySessionRepository(),
        jobs=memory.InMemoryJobRepository(),
        commands=memory.InMemoryDeviceCommandRepository(),
    )


def _postgres_repositories(settings: Settings) -> tuple[_Repositories, ConnectionPool]:
    assert settings.database_url is not None  # validate_settings guarantees it
    pool = postgres.create_pool(
        settings.database_url.get_secret_value(), max_size=settings.database_pool_max_size
    )
    try:
        postgres.check_schema_current_with(pool)
    except Exception:
        pool.close()
        raise
    repos = postgres.PostgresRepositories.from_pool(pool)
    return (
        _Repositories(
            projects=repos.projects,
            memberships=repos.memberships,
            devices=repos.devices,
            sessions=repos.sessions,
            jobs=repos.jobs,
            commands=repos.commands,
        ),
        pool,
    )


def build_container(settings: Settings) -> Container:
    validate_settings(settings)
    if settings.app_env not in LOCAL_ONLY_ENVS:
        # TODO(workstream C): SQS job/command queues and the AppSync realtime publisher. Until
        # they exist a deployed API would accept jobs and commands that nothing ever runs.
        raise NotImplementedError(
            "queue and realtime adapters for deployed environments are not implemented yet"
        )

    pool: ConnectionPool | None = None
    if settings.repository_backend is RepositoryBackend.POSTGRES:
        repos, pool = _postgres_repositories(settings)
    else:
        repos = _memory_repositories()

    authorizer = Authorizer(repos.memberships)
    return Container(
        settings=settings,
        authorizer=authorizer,
        projects=ProjectService(repos.projects, repos.memberships, authorizer),
        devices=DeviceService(repos.devices, authorizer),
        sessions=SessionService(
            repos.sessions, repos.devices, authorizer, memory.RecordingRealtimePublisher()
        ),
        jobs=JobService(repos.jobs, repos.devices, memory.InMemoryJobQueue(), authorizer),
        commands=CommandService(
            repos.commands, repos.devices, memory.InMemoryCommandQueue(), authorizer
        ),
        pool=pool,
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


def get_command_service(container: ContainerDep) -> CommandService:
    return container.commands


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
DeviceServiceDep = Annotated[DeviceService, Depends(get_device_service)]
SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
JobServiceDep = Annotated[JobService, Depends(get_job_service)]
CommandServiceDep = Annotated[CommandService, Depends(get_command_service)]
