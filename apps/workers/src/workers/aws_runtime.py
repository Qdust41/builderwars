"""Lambda wiring: build each worker once per execution environment from the environment.

Repositories come from PostgreSQL in AWS (``REPOSITORY_BACKEND=postgres``; in-memory only under
``APP_ENV=local|test``, which ``validate_worker_settings`` enforces). AWS clients come from
``client_factory`` (``boto3.client`` in Lambda, stubbed clients in tests).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import SecretStr

from ai_platform.autofix import AutoFixWorker, default_clients
from application.adapters import memory, postgres
from application.ports import (
    AutoFixRunRepository,
    AutoFixSettingsRepository,
    DeviceCommandRepository,
    JobRepository,
)
from application.ports.repositories import (
    DeviceRepository,
    ProcessedMessageStore,
    SequenceTracker,
    TelemetryRepository,
)
from application.services import AutoFixTrigger, DeviceEventPublisher, DeviceMessageIngestService
from aws_adapters import (
    AppSyncEventsPublisher,
    IotDataCommandPublisher,
    S3RawMessageStore,
    SecretsManagerAutoFixSecretStore,
    SqsAutoFixQueue,
    database_url_from_secret,
    shared_autofix_secrets,
)
from domain.jobs import JobType
from workers.handlers import BackgroundJobHandler, CommandDispatchHandler, DeviceMessageHandler
from workers.handlers.background_job import JobExecutor
from workers.settings import (
    RepositoryBackend,
    UnsafeConfigurationError,
    WorkerSettings,
    validate_worker_settings,
)

ClientFactory = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class WorkerRepositories:
    devices: DeviceRepository
    processed: ProcessedMessageStore
    sequences: SequenceTracker
    telemetry: TelemetryRepository
    commands: DeviceCommandRepository
    jobs: JobRepository
    autofix_settings: AutoFixSettingsRepository
    autofix_runs: AutoFixRunRepository
    close: Callable[[], None] = field(default=lambda: None)


def resolve_settings(settings: WorkerSettings, client_factory: ClientFactory) -> WorkerSettings:
    """Fill DATABASE_URL from DATABASE_SECRET_ARN (the RDS secret) when only the ARN is set."""
    if settings.database_url is None and settings.database_secret_arn:
        url = database_url_from_secret(
            client_factory("secretsmanager"), settings.database_secret_arn
        )
        settings = settings.model_copy(update={"database_url": SecretStr(url)})
    return validate_worker_settings(settings)


def open_repositories(settings: WorkerSettings) -> WorkerRepositories:
    if settings.repository_backend is RepositoryBackend.POSTGRES:
        assert settings.database_url is not None  # validate_worker_settings guarantees it
        pool = postgres.create_pool(
            settings.database_url.get_secret_value(),
            max_size=settings.database_pool_max_size,
            name="builderwars-worker",
        )
        try:
            postgres.check_schema_current_with(pool)
        except Exception:
            pool.close()
            raise
        repos = postgres.PostgresRepositories.from_pool(pool)
        return WorkerRepositories(
            devices=repos.devices,
            processed=repos.processed,
            sequences=repos.sequences,
            telemetry=repos.telemetry,
            commands=repos.commands,
            jobs=repos.jobs,
            autofix_settings=repos.autofix_settings,
            autofix_runs=repos.autofix_runs,
            close=repos.close,
        )
    return WorkerRepositories(  # LOCAL/TEST ONLY (validated above)
        devices=memory.InMemoryDeviceRepository(),
        processed=memory.InMemoryProcessedMessageStore(),
        sequences=memory.InMemorySequenceTracker(),
        telemetry=memory.InMemoryTelemetryRepository(),
        commands=memory.InMemoryDeviceCommandRepository(),
        jobs=memory.InMemoryJobRepository(),
        autofix_settings=memory.InMemoryAutoFixSettingsRepository(),
        autofix_runs=memory.InMemoryAutoFixRunRepository(),
    )


def _require(value: str | None, name: str) -> str:
    if not value:
        raise UnsafeConfigurationError(f"{name} must be set for this worker")
    return value


def device_events(settings: WorkerSettings) -> DeviceEventPublisher | None:
    """Realtime device events over AppSync Events, or ``None`` when EVENTS_HTTP_DNS is unset."""
    if not settings.events_http_dns:
        return None
    import boto3  # only in AWS; credentials are the function role's, refreshed per publish

    return DeviceEventPublisher(
        AppSyncEventsPublisher(
            http_dns=settings.events_http_dns,
            region=_require(settings.aws_region, "AWS_REGION"),
            credentials=boto3.Session().get_credentials,
        )
    )


def build_device_ingest(
    settings: WorkerSettings, repos: WorkerRepositories, client_factory: ClientFactory
) -> DeviceMessageHandler:
    bucket = _require(settings.device_data_bucket, "DEVICE_DATA_BUCKET")
    ingest = DeviceMessageIngestService(
        devices=repos.devices,
        processed=repos.processed,
        raw_store=S3RawMessageStore(client_factory("s3"), bucket),
        telemetry=repos.telemetry,
        sequences=repos.sequences,
        commands=repos.commands,
        events=device_events(settings),
        errors=autofix_trigger(settings, repos, client_factory),
    )
    return DeviceMessageHandler(ingest)


def autofix_trigger(
    settings: WorkerSettings, repos: WorkerRepositories, client_factory: ClientFactory
) -> AutoFixTrigger | None:
    """Starts auto-fix runs from ingested errors, or ``None`` when AUTOFIX_QUEUE_URL is unset."""
    if not settings.autofix_queue_url:
        return None
    return AutoFixTrigger(
        settings=repos.autofix_settings,
        runs=repos.autofix_runs,
        queue=SqsAutoFixQueue(client_factory("sqs"), settings.autofix_queue_url),
        devices=repos.devices,
    )


def build_autofix_worker(
    settings: WorkerSettings, repos: WorkerRepositories, client_factory: ClientFactory
) -> AutoFixWorker:
    prefix = _require(settings.autofix_secret_prefix, "AUTOFIX_SECRET_PREFIX")
    secretsmanager = client_factory("secretsmanager")
    return AutoFixWorker(
        runs=repos.autofix_runs,
        settings=repos.autofix_settings,
        secrets=SecretsManagerAutoFixSecretStore(secretsmanager, prefix),
        shared=(
            shared_autofix_secrets(secretsmanager, settings.autofix_shared_secret_arn)
            if settings.autofix_shared_secret_arn
            else None
        ),
        telemetry=repos.telemetry,
        # Deployed workers only call public endpoints (no localhost / VPC / link-local).
        clients=default_clients(allow_private_endpoints=settings.app_env in {"local", "test"}),
    )


def build_command_dispatch(
    settings: WorkerSettings, repos: WorkerRepositories, client_factory: ClientFactory
) -> CommandDispatchHandler:
    endpoint = _require(settings.iot_data_endpoint, "IOT_DATA_ENDPOINT")
    client = client_factory("iot-data", endpoint_url=f"https://{endpoint}")
    return CommandDispatchHandler(
        repos.commands, IotDataCommandPublisher(client), device_events(settings)
    )


def build_job_worker(
    settings: WorkerSettings,
    repos: WorkerRepositories,
    client_factory: ClientFactory,
    executors: dict[JobType, JobExecutor] | None = None,
) -> BackgroundJobHandler:
    # No executors exist yet (AI runs, builds and tests are workstreams H and I), so queued jobs
    # are marked failed with "not implemented" rather than left queued forever.
    return BackgroundJobHandler(repos.jobs, executors or {})
