"""Dependency wiring. Routes depend on services via FastAPI ``Depends``; services depend on ports.

``build_container`` is the single place that chooses adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from api.auth import CognitoTokenVerifier, InvalidTokenError, JwksUrlKeySource
from api.settings import AuthMode, RepositoryBackend, Settings, validate_settings
from application.adapters import memory
from application.ports import UserDirectory
from application.services import (
    Authorizer,
    CommandService,
    DeviceService,
    JobService,
    ProjectService,
    SessionService,
)
from domain.users import User


@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: str


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    token_verifier: CognitoTokenVerifier | None
    users: UserDirectory
    # Dev-header mode only: every X-Dev-User is registered here as <user>@example.com.
    dev_users: memory.InMemoryUserDirectory | None
    authorizer: Authorizer
    projects: ProjectService
    devices: DeviceService
    sessions: SessionService
    jobs: JobService
    commands: CommandService


def build_container(
    settings: Settings,
    *,
    token_verifier: CognitoTokenVerifier | None = None,
    users: UserDirectory | None = None,
) -> Container:
    """``token_verifier`` and ``users`` override the Cognito adapters (tests, local JWKS)."""
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

    dev_users: memory.InMemoryUserDirectory | None = None
    if settings.auth_mode is AuthMode.COGNITO:
        token_verifier = token_verifier or _cognito_verifier(settings)
        if users is None:
            from api.cognito_users import CognitoUserDirectory  # boto3 only when needed

            assert settings.cognito_user_pool_id  # checked by validate_settings
            users = CognitoUserDirectory(
                user_pool_id=settings.cognito_user_pool_id, region=settings.cognito_region
            )
    elif users is None:
        users = dev_users = memory.InMemoryUserDirectory()

    return Container(
        settings=settings,
        token_verifier=token_verifier,
        users=users,
        dev_users=dev_users,
        authorizer=authorizer,
        projects=ProjectService(projects, memberships, authorizer, users),
        devices=DeviceService(devices, authorizer),
        sessions=SessionService(sessions, devices, authorizer, memory.RecordingRealtimePublisher()),
        jobs=JobService(jobs, devices, memory.InMemoryJobQueue(), authorizer),
        commands=CommandService(
            memory.InMemoryDeviceCommandRepository(),
            devices,
            memory.InMemoryCommandQueue(),
            authorizer,
        ),
    )


def _cognito_verifier(settings: Settings) -> CognitoTokenVerifier:
    assert settings.cognito_app_client_id  # checked by validate_settings
    return CognitoTokenVerifier(
        issuer=settings.cognito_issuer,
        client_id=settings.cognito_app_client_id,
        keys=JwksUrlKeySource(settings.cognito_jwks_endpoint),
    )


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


def get_current_user(
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    mode = container.settings.auth_mode
    if mode is AuthMode.DEV_HEADER:
        # LOCAL ONLY: validate_settings() forbids this mode outside local/test.
        if not x_dev_user:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing X-Dev-User header")
        if container.dev_users is not None and container.dev_users.get(x_dev_user) is None:
            container.dev_users.add(User(user_id=x_dev_user, email=f"{x_dev_user}@example.com"))
        return CurrentUser(user_id=x_dev_user)

    verifier = container.token_verifier
    if verifier is None:  # pragma: no cover - build_container always sets it in cognito mode
        raise _unauthorized("authentication is not configured")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("missing bearer token")
    try:
        verified = verifier.verify(token.strip())
    except InvalidTokenError:
        raise _unauthorized("invalid or expired token") from None
    return CurrentUser(user_id=verified.user_id)


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
