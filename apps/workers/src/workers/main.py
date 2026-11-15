"""Worker entry points.

Local:   uv run python -m workers.main messages.jsonl   (or pipe JSON lines on stdin)
         REPOSITORY_BACKEND=postgres DATABASE_URL=... stores into PostgreSQL instead of memory.
Lambda:  workers.main.device_message_lambda_handler / command_dispatch_lambda_handler /
         job_lambda_handler / migrate_lambda_handler (wired in workers.aws_runtime)
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from typing import Any

import boto3
from pydantic import ValidationError

from application.adapters import memory, postgres
from application.services import DeviceMessageIngestService
from workers import aws_runtime
from workers.aws_runtime import ClientFactory
from workers.consumers import LocalHarness, process_sqs_batch, read_jsonl
from workers.handlers import (
    BackgroundJobHandler,
    CommandDispatchHandler,
    CommandMessage,
    DeviceMessageHandler,
    IncomingDeviceMessage,
)
from workers.handlers.background_job import JobMessage
from workers.settings import (
    RepositoryBackend,
    UnsafeConfigurationError,
    WorkerSettings,
    validate_worker_settings,
)

log = logging.getLogger(__name__)


def build_local_device_handler() -> tuple[DeviceMessageHandler, memory.InMemoryTelemetryRepository]:
    """IN-MEMORY wiring for local development only."""
    telemetry = memory.InMemoryTelemetryRepository()
    ingest = DeviceMessageIngestService(
        devices=memory.InMemoryDeviceRepository(),
        processed=memory.InMemoryProcessedMessageStore(),
        raw_store=memory.InMemoryRawMessageStore(),
        telemetry=telemetry,
        sequences=memory.InMemorySequenceTracker(),
    )
    return DeviceMessageHandler(ingest), telemetry


def build_postgres_device_handler(
    settings: WorkerSettings,
) -> tuple[DeviceMessageHandler, postgres.PostgresRepositories]:
    """PostgreSQL wiring: every ingest port, including raw/quarantine rows, in one database.

    The caller owns the pool (``repos.close()``); a Lambda keeps it for the container's life.
    """
    validate_worker_settings(settings)
    assert settings.database_url is not None
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
    ingest = DeviceMessageIngestService(
        devices=repos.devices,
        processed=repos.processed,
        raw_store=repos.raw_messages,
        telemetry=repos.telemetry,
        sequences=repos.sequences,
        commands=repos.commands,
    )
    return DeviceMessageHandler(ingest), repos


# --- AWS Lambda entry points ---------------------------------------------------------------
# Each worker is built once per Lambda execution environment (cold start) and reused. The
# builders refuse in-memory repositories outside APP_ENV=local|test and fail fast when a
# required setting (bucket, IoT endpoint, database) is missing.

_client_factory: ClientFactory = boto3.client
_runtimes: dict[str, tuple[Any, aws_runtime.WorkerRepositories]] = {}


def set_client_factory(factory: ClientFactory) -> None:
    """Swap how AWS clients are made (tests pass stubbed clients). Clears built workers."""
    global _client_factory
    _client_factory = factory
    reset_lambda_runtimes()


def reset_lambda_runtimes() -> None:
    for _, repos in _runtimes.values():
        repos.close()
    _runtimes.clear()


def lambda_runtime(name: str) -> tuple[Any, aws_runtime.WorkerRepositories]:
    """The (handler, repositories) pair for one worker, built on first use."""
    if name not in _runtimes:
        builder = _BUILDERS[name]
        settings = aws_runtime.resolve_settings(WorkerSettings(), _client_factory)
        repos = aws_runtime.open_repositories(settings)
        try:
            handler = builder(settings, repos, _client_factory)
        except Exception:
            repos.close()
            raise
        _runtimes[name] = (handler, repos)
    return _runtimes[name]


_BUILDERS: dict[str, Callable[..., Any]] = {
    "ingest": aws_runtime.build_device_ingest,
    "commands": aws_runtime.build_command_dispatch,
    "jobs": aws_runtime.build_job_worker,
}


def _acknowledge_invalid[M](
    parse: Callable[[dict[str, Any]], M], handle: Callable[[M], object]
) -> Callable[[dict[str, Any]], object]:
    """A record that fails validation can never succeed: log and acknowledge it (no retry)."""

    def run(body: dict[str, Any]) -> object:
        try:
            message = parse(body)
        except ValidationError as exc:
            log.error("invalid queue message acknowledged without retry: %s", exc.errors()[:3])
            return None
        return handle(message)

    return run


def device_message_lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    handler: DeviceMessageHandler = lambda_runtime("ingest")[0]
    return process_sqs_batch(
        event, _acknowledge_invalid(IncomingDeviceMessage.model_validate, handler.handle)
    )


def job_lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    handler: BackgroundJobHandler = lambda_runtime("jobs")[0]
    return process_sqs_batch(event, _acknowledge_invalid(JobMessage.model_validate, handler.handle))


def command_dispatch_lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    handler: CommandDispatchHandler = lambda_runtime("commands")[0]
    return process_sqs_batch(
        event, _acknowledge_invalid(CommandMessage.model_validate, handler.handle)
    )


def migrate_lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Apply pending schema migrations. Invoked by hand after a deploy (docs/aws-deployment.md);
    the other workers refuse to start until the schema is current."""
    settings = aws_runtime.resolve_settings(WorkerSettings(), _client_factory)
    if settings.repository_backend is not RepositoryBackend.POSTGRES:
        raise UnsafeConfigurationError("migrations need REPOSITORY_BACKEND=postgres")
    assert settings.database_url is not None
    applied = postgres.migrate(settings.database_url.get_secret_value())
    return {"applied": applied}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run device messages through the local harness")
    parser.add_argument("input", nargs="?", help="JSON-lines file (default: stdin)")
    args = parser.parse_args(argv)

    settings = validate_worker_settings(WorkerSettings())
    memory_telemetry: memory.InMemoryTelemetryRepository | None = None
    if settings.repository_backend is RepositoryBackend.POSTGRES:
        handler, _ = build_postgres_device_handler(settings)
    else:
        handler, memory_telemetry = build_local_device_handler()
    harness = LocalHarness(handler)
    if args.input:
        with open(args.input, encoding="utf-8") as fh:
            counts = harness.run(read_jsonl(fh))
    else:
        counts = harness.run(read_jsonl(sys.stdin))

    for result in harness.results:
        reason = f" ({result.reason.value}: {result.detail})" if result.reason else ""
        print(f"{result.outcome.value:<9} {result.device_id} {result.message_id}{reason}")
    summary = ", ".join(f"{k.value}={v}" for k, v in sorted(counts.items()))
    if memory_telemetry is not None:
        summary += (
            f"; telemetry samples={len(memory_telemetry.telemetry)}; "
            f"events={len(memory_telemetry.events)}"
        )
    else:
        summary += "; stored in PostgreSQL"
    print(f"summary: {summary}")
    return 0


__all__ = [
    "IncomingDeviceMessage",
    "build_local_device_handler",
    "build_postgres_device_handler",
    "command_dispatch_lambda_handler",
    "device_message_lambda_handler",
    "job_lambda_handler",
    "main",
    "migrate_lambda_handler",
    "process_sqs_batch",
]

if __name__ == "__main__":
    raise SystemExit(main())
