"""Worker entry points.

Local:   uv run python -m workers.main messages.jsonl   (or pipe JSON lines on stdin)
         REPOSITORY_BACKEND=postgres DATABASE_URL=... stores into PostgreSQL instead of memory.
Lambda:  workers.main.device_message_lambda_handler / job_lambda_handler (wiring TODO)
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from application.adapters import memory, postgres
from application.services import DeviceMessageIngestService
from workers.consumers import LocalHarness, process_sqs_batch, read_jsonl
from workers.handlers import DeviceMessageHandler, IncomingDeviceMessage
from workers.settings import (
    RepositoryBackend,
    WorkerSettings,
    validate_worker_settings,
)


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


def device_message_lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    # TODO: build the handler once per container with PostgreSQL/S3 adapters. Refuse to fall
    # back to in-memory adapters in AWS.
    raise NotImplementedError("AWS adapters for the device ingest worker are not implemented")


def job_lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    raise NotImplementedError("AWS adapters for the job worker are not implemented")


def command_dispatch_lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    # TODO: PostgreSQL command repository + IoT data-plane publisher (iot-data Publish).
    raise NotImplementedError("AWS adapters for the command dispatcher are not implemented")


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
    "process_sqs_batch",
]

if __name__ == "__main__":
    raise SystemExit(main())
