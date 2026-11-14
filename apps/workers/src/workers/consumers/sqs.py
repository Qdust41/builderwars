"""SQS batch consumer with partial batch responses.

Retry / dead-letter behaviour:

* The Lambda event source mapping must enable ``ReportBatchItemFailures``.
* A record that raises (transient error: DB down, throttling) is reported in
  ``batchItemFailures`` and becomes visible again after the visibility timeout.
* After ``maxReceiveCount`` attempts SQS moves it to the queue's DLQ (see
  infrastructure/stacks/messaging.py); an alarm fires when the DLQ is non-empty.
* Permanently invalid messages are NOT raised: handlers acknowledge them (and log/quarantine)
  so they don't burn retries.
* Because delivery is at-least-once, every handler must be idempotent.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

RecordHandler = Callable[[dict[str, Any]], object]


def process_sqs_batch(event: dict[str, Any], handle: RecordHandler) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        message_id = record.get("messageId", "<unknown>")
        try:
            body = json.loads(record["body"])
        except (KeyError, json.JSONDecodeError):
            log.error("unparseable SQS record %s; acknowledging (permanent)", message_id)
            continue
        try:
            handle(body)
        except Exception:
            log.exception("transient failure on record %s; will retry", message_id)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
