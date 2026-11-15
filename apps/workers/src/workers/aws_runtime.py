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

from application.adapters import memory, postgres
from application.ports import DeviceCommandRepository, JobRepository
from application.ports.repositories import (
    DeviceRepository,
    ProcessedMessageStore,
    SequenceTracker,
    TelemetryRepository,
)
from application.services import DeviceMessageIngestService
from aws_adapters import IotDataCommandPublisher, S3RawMessageStore, database_url_from_secret
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
            close=repos.close,
        )
    return WorkerRepositories(  # LOCAL/TEST ONLY (validated above)
        devices=memory.InMemoryDeviceRepository(),
        processed=memory.InMemoryProcessedMessageStore(),
        sequences=memory.InMemorySequenceTracker(),
        telemetry=memory.InMemoryTelemetryRepository(),
        commands=memory.InMemoryDeviceCommandRepository(),
        jobs=memory.InMemoryJobRepository(),
    )


def _require(value: str | None, name: str) -> str:
    if not value:
        raise UnsafeConfigurationError(f"{name} must be set for this worker")
    return value


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
    )
    return DeviceMessageHandler(ingest)


def build_command_dispatch(
    settings: WorkerSettings, repos: WorkerRepositories, client_factory: ClientFactory
) -> CommandDispatchHandler:
    endpoint = _require(settings.iot_data_endpoint, "IOT_DATA_ENDPOINT")
    client = client_factory("iot-data", endpoint_url=f"https://{endpoint}")
    return CommandDispatchHandler(repos.commands, IotDataCommandPublisher(client))


def build_job_worker(
    settings: WorkerSettings,
    repos: WorkerRepositories,
    client_factory: ClientFactory,
    executors: dict[JobType, JobExecutor] | None = None,
) -> BackgroundJobHandler:
    # No executors exist yet (AI runs, builds and tests are workstreams H and I), so queued jobs
    # are marked failed with "not implemented" rather than left queued forever.
    return BackgroundJobHandler(repos.jobs, executors or {})
