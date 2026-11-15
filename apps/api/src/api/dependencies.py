"""Dependency wiring. Routes depend on services via FastAPI ``Depends``; services depend on ports.

``build_container`` is the single place that chooses adapters.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

import boto3
from fastapi import Depends, Header, HTTPException, Request, status
from psycopg_pool import ConnectionPool
from pydantic import SecretStr

from api.auth import CognitoTokenVerifier, InvalidTokenError, JwksUrlKeySource
from api.settings import (
    LOCAL_ONLY_ENVS,
    AuthMode,
    RepositoryBackend,
    Settings,
    validate_settings,
)
from application.adapters import memory, postgres
from application.ports import CommandQueue, JobQueue, RealtimePublisher, UserDirectory
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
from aws_adapters import (
    AppSyncEventsPublisher,
    SqsCommandQueue,
    SqsJobQueue,
    database_url_from_secret,
)
from domain.users import User

ClientFactory = Callable[..., Any]


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


@dataclass(frozen=True, slots=True)
class _Messaging:
    job_queue: JobQueue
    command_queue: CommandQueue
    realtime: RealtimePublisher


def _local_messaging() -> _Messaging:
    """LOCAL/TEST ONLY: queues and realtime events stay in process."""
    return _Messaging(
        job_queue=memory.InMemoryJobQueue(),
        command_queue=memory.InMemoryCommandQueue(),
        realtime=memory.RecordingRealtimePublisher(),
    )


def _aws_messaging(settings: Settings, client_factory: ClientFactory) -> _Messaging:
    # validate_settings guarantees these outside local/test.
    assert settings.jobs_queue_url
    assert settings.commands_queue_url
    assert settings.events_http_dns
    assert settings.aws_region
    sqs = client_factory("sqs")
    return _Messaging(
        job_queue=SqsJobQueue(sqs, settings.jobs_queue_url),
        command_queue=SqsCommandQueue(sqs, settings.commands_queue_url),
        realtime=AppSyncEventsPublisher(
            http_dns=settings.events_http_dns,
            region=settings.aws_region,
            credentials=boto3.Session().get_credentials,
        ),
    )


def resolve_database_url(settings: Settings, client_factory: ClientFactory) -> Settings:
    """Fill DATABASE_URL from DATABASE_SECRET_ARN (the RDS secret) when only the ARN is set."""
    if settings.database_url is None and settings.database_secret_arn:
        url = database_url_from_secret(
            client_factory("secretsmanager"), settings.database_secret_arn
        )
        settings = settings.model_copy(update={"database_url": SecretStr(url)})
    return settings


def build_container(
    settings: Settings,
    *,
    token_verifier: CognitoTokenVerifier | None = None,
    users: UserDirectory | None = None,
    client_factory: ClientFactory = boto3.client,
    messaging: _Messaging | None = None,
) -> Container:
    """Choose adapters. In-memory everything locally; SQS + AppSync Events elsewhere.

    ``token_verifier``, ``users`` and ``messaging`` override the Cognito, queue and realtime
    adapters (tests, local JWKS).
    """
    settings = validate_settings(resolve_database_url(settings, client_factory))
    if messaging is None:
        messaging = (
            _local_messaging()
            if settings.app_env in LOCAL_ONLY_ENVS
            else _aws_messaging(settings, client_factory)
        )

    pool: ConnectionPool | None = None
    if settings.repository_backend is RepositoryBackend.POSTGRES:
        repos, pool = _postgres_repositories(settings)
    else:
        repos = _memory_repositories()
    authorizer = Authorizer(repos.memberships)

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
        projects=ProjectService(repos.projects, repos.memberships, authorizer, users),
        devices=DeviceService(repos.devices, authorizer),
        sessions=SessionService(repos.sessions, repos.devices, authorizer, messaging.realtime),
        jobs=JobService(repos.jobs, repos.devices, messaging.job_queue, authorizer),
        commands=CommandService(repos.commands, repos.devices, messaging.command_queue, authorizer),
        pool=pool,
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
