"""Turn saved board output into protocol messages for ``builderwars upload``.

Two kinds of file are accepted:

* **JSON lines** (``.jsonl`` / ``.json`` / anything not ``.csv``): one ``{"topic", "payload"}``
  per line, exactly what ``builderwars sim`` and ``builderwars run`` print. Telemetry, logs,
  status and events all upload; cloud-to-device lines (commands) are skipped.
* **Log CSV** (``.csv``): the file the runtime keeps under ``<state-dir>/logs/<id>.csv``
  (columns ``board_runtime.logging.CSV_COLUMNS``). Each row becomes the ``log`` envelope it
  was written from, with the same ``message_id``, so a log that also went up live is
  recognised as a duplicate and stored once.
* **Logger CSV** (``.csv`` with the ``logger_real`` header): what ``run --logger real`` and
  ``scripts/wili_code/src/logger_real.py`` write (e.g. ``combined_gpio_imu.csv``). Rows become
  telemetry samples (the same readings ``run --logger real`` sends live), batched under the
  envelope's size limit. Message ids are derived from the device and the samples' times, so
  uploading the same file twice stores it once.

Every message is re-addressed to the device being uploaded to (topic and envelope
``device_id``), because files recorded before the board was registered carry a local id such
as ``dev-local``. Lines that cannot be read are reported, not uploaded.
"""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from board_runtime.batching import TelemetryBatcher
from board_runtime.hardware.logger_real import is_logger_csv, readings_from_csv_row
from board_runtime.logging import CSV_COLUMNS
from device_protocol import CURRENT_SCHEMA_VERSION, MessageType, topic_for_message
from device_protocol.schemas import TELEMETRY_MAX_SAMPLES
from device_protocol.topics import DEVICE_TO_CLOUD_CHANNELS, InvalidTopicError, parse_topic

_NULLABLE_INTS = frozenset({"sequence_number"})
_OPTIONAL_TEXT = frozenset({"firmware_version", "hardware_model"})


@dataclass
class ReadResult:
    messages: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # human-readable reasons, with line numbers


def read_messages(path: Path, device_id: str) -> ReadResult:
    if path.suffix.lower() == ".csv":
        return _read_csv(path, device_id)
    return _read_jsonl(path, device_id)


def _readdress(payload: dict[str, Any], device_id: str) -> dict[str, Any]:
    return {**payload, "device_id": device_id}


def _read_jsonl(path: Path, device_id: str) -> ReadResult:
    result = ReadResult()
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                topic, payload = item["topic"], item["payload"]
                _, channel = parse_topic(str(topic))
                if not isinstance(payload, dict):
                    raise ValueError("payload is not an object")
            except (ValueError, KeyError, TypeError, InvalidTopicError) as exc:
                result.skipped.append(f"line {number}: not a board message ({exc})")
                continue
            if channel not in DEVICE_TO_CLOUD_CHANNELS:
                continue  # commands the cloud sent the board; nothing to upload
            try:
                message_type = MessageType(str(payload["message_type"]))
                new_topic = topic_for_message(device_id, message_type)
            except (ValueError, KeyError, InvalidTopicError) as exc:
                result.skipped.append(f"line {number}: {exc}")
                continue
            result.messages.append({"topic": new_topic, "payload": _readdress(payload, device_id)})
    return result


def _read_csv(path: Path, device_id: str) -> ReadResult:
    result = ReadResult()
    topic = topic_for_message(device_id, MessageType.LOG)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if is_logger_csv(reader.fieldnames):
            return _read_logger_csv(reader, device_id)
        if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
            raise ValueError(
                f"{path}: not a builderwars log CSV (expected columns {', '.join(CSV_COLUMNS)}) "
                "nor a logger_real CSV"
            )
        for number, row in enumerate(reader, start=2):
            try:
                payload: dict[str, Any] = {
                    "message_id": row["message_id"],
                    "schema_version": int(row["schema_version"]),
                    "device_id": device_id,
                    "timestamp": row["timestamp"],
                    "message_type": MessageType.LOG.value,
                    "payload": {"level": row["level"], "message": row["message"]},
                }
                if row.get("logger"):
                    payload["payload"]["logger"] = row["logger"]
                for column in _NULLABLE_INTS:
                    if row.get(column):
                        payload[column] = int(row[column])
                for column in _OPTIONAL_TEXT:
                    if row.get(column):
                        payload[column] = row[column]
            except (ValueError, KeyError, TypeError) as exc:
                result.skipped.append(f"row {number}: {exc}")
                continue
            result.messages.append({"topic": topic, "payload": payload})
    return result


# Fixed namespace so the same samples always get the same message id (re-uploads dedupe).
_LOGGER_NAMESPACE = uuid.UUID("6f2b3c1e-6a39-4f0c-9d0e-3b1f4c2a7e51")


def _sample_time(text: str) -> datetime:
    """The script writes local time without a zone (``datetime.now().isoformat()``)."""
    when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return when.astimezone() if when.tzinfo is None else when


def _read_logger_csv(reader: csv.DictReader[str], device_id: str) -> ReadResult:
    result = ReadResult()
    topic = topic_for_message(device_id, MessageType.TELEMETRY)
    batcher = TelemetryBatcher(window_s=float("inf"), max_samples=TELEMETRY_MAX_SAMPLES)
    previous: datetime | None = None

    def emit(batch: dict[str, Any] | None) -> None:
        if not batch:
            return
        samples = batch["samples"]
        key = f"{device_id}|{samples[0]['ts']}|{samples[-1]['ts']}|{len(samples)}"
        payload = {
            "message_id": str(uuid.uuid5(_LOGGER_NAMESPACE, key)),
            "schema_version": CURRENT_SCHEMA_VERSION,
            "device_id": device_id,
            "timestamp": samples[-1]["ts"],
            "message_type": MessageType.TELEMETRY.value,
            "payload": batch,
        }
        result.messages.append({"topic": topic, "payload": payload})

    for number, row in enumerate(reader, start=2):
        try:
            at = _sample_time(row["timestamp"])
            readings = readings_from_csv_row(row)
        except (ValueError, KeyError, TypeError) as exc:
            result.skipped.append(f"row {number}: {exc}")
            continue
        if not readings:
            errors = "; ".join(e for e in (row.get("gpio_error"), row.get("imu_error")) if e)
            result.skipped.append(f"row {number}: no readings ({errors or 'empty row'})")
            continue
        if previous is not None and at < previous:
            emit(batcher.flush())  # samples in a batch must be in time order
        previous = at
        emit(batcher.add(readings, at=at, now=0.0))
    emit(batcher.flush())
    return result
