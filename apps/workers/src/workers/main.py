"""Worker entry points.

Local:   uv run python -m workers.main messages.jsonl   (or pipe JSON lines on stdin)
Lambda:  workers.main.device_message_lambda_handler / job_lambda_handler (wiring TODO)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from typing import Any

from application.adapters import memory
from application.services import DeviceMessageIngestService
from device_protocol import parse_topic
from device_protocol.topics import InvalidTopicError
from domain.devices import Device
from workers.consumers import LocalHarness, process_sqs_batch, read_jsonl
from workers.handlers import DeviceMessageHandler, IncomingDeviceMessage


def build_local_device_handler(
    device_ids: Iterable[str] = (),
) -> tuple[DeviceMessageHandler, memory.InMemoryTelemetryRepository]:
    """IN-MEMORY wiring for local development only.

    Ingest rejects unregistered devices, so ``device_ids`` are registered up front (in a
    throwaway local project) to stand in for devices registered through the API.
    """
    devices = memory.InMemoryDeviceRepository()
    for device_id in device_ids:
        devices.add(
            Device(
                id=device_id,
                project_id="prj_local",
                display_name=device_id,
                hardware_model="freewili-1-og",
            )
        )
    telemetry = memory.InMemoryTelemetryRepository()
    ingest = DeviceMessageIngestService(
        devices=devices,
        processed=memory.InMemoryProcessedMessageStore(),
        raw_store=memory.InMemoryRawMessageStore(),
        telemetry=telemetry,
        sequences=memory.InMemorySequenceTracker(),
    )
    return DeviceMessageHandler(ingest), telemetry


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

    if args.input:
        with open(args.input, encoding="utf-8") as fh:
            messages = list(read_jsonl(fh))
    else:
        messages = list(read_jsonl(sys.stdin))

    # LOCAL ONLY: treat every device in the input as registered (see build_local_device_handler).
    handler, telemetry = build_local_device_handler(_topic_device_ids(m.topic for m in messages))
    harness = LocalHarness(handler)
    counts = harness.run(messages)

    for result in harness.results:
        reason = f" ({result.reason.value}: {result.detail})" if result.reason else ""
        print(f"{result.outcome.value:<9} {result.device_id} {result.message_id}{reason}")
    summary = ", ".join(f"{k.value}={v}" for k, v in sorted(counts.items()))
    print(
        f"summary: {summary}; telemetry samples={len(telemetry.telemetry)}; "
        f"events={len(telemetry.events)}"
    )
    return 0


def _topic_device_ids(topics: Iterable[str]) -> set[str]:
    ids = set()
    for topic in topics:
        try:
            ids.add(parse_topic(topic)[0])
        except InvalidTopicError:
            continue
    return ids


__all__ = [
    "IncomingDeviceMessage",
    "build_local_device_handler",
    "command_dispatch_lambda_handler",
    "device_message_lambda_handler",
    "job_lambda_handler",
    "main",
    "process_sqs_batch",
]

if __name__ == "__main__":
    raise SystemExit(main())
