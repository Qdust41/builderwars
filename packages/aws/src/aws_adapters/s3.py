"""Raw device message retention in S3 (``RawDeviceMessageStore``).

Layout (the bucket's lifecycle rules expire both prefixes, see infrastructure/stacks/storage.py):

* ``raw/{device_id}/{yyyy}/{mm}/{dd}/{message_id}.json`` for accepted messages. The key is
  deterministic, so a redelivered message overwrites the same object (idempotent).
* ``rejected/{device_id}/{yyyy}/{mm}/{dd}/{received_ms}-{sha256[:16]}.bin`` for quarantined
  bodies, with the rejection reason in the object metadata. ``device_id`` is ``_unknown`` when
  the topic had none and ``_invalid`` when it is not a valid id (it comes from the topic, which
  may be malformed on a rejected message).
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from device_protocol.topics import DEVICE_ID_PATTERN

_DEVICE_ID_RE = re.compile(DEVICE_ID_PATTERN)
RAW_PREFIX = "raw"
REJECTED_PREFIX = "rejected"


def _day(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y/%m/%d")


def _safe_device(device_id: str | None) -> str:
    if device_id is None:
        return "_unknown"
    return device_id if _DEVICE_ID_RE.fullmatch(device_id) else "_invalid"


def raw_key(device_id: str, message_id: str, received_at: datetime) -> str:
    return f"{RAW_PREFIX}/{_safe_device(device_id)}/{_day(received_at)}/{message_id}.json"


def rejected_key(device_id: str | None, received_at: datetime, body: bytes) -> str:
    millis = int(received_at.timestamp() * 1000)
    digest = hashlib.sha256(body).hexdigest()[:16]
    return f"{REJECTED_PREFIX}/{_safe_device(device_id)}/{_day(received_at)}/{millis}-{digest}.bin"


class S3RawMessageStore:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def put(self, *, device_id: str, message_id: str, received_at: datetime, body: bytes) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=raw_key(device_id, message_id, received_at),
            Body=body,
            ContentType="application/json",
        )

    def quarantine(
        self, *, device_id: str | None, received_at: datetime, body: bytes, reason: str
    ) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=rejected_key(device_id, received_at, body),
            Body=body,
            ContentType="application/octet-stream",
            Metadata={"reason": reason[:256]},
        )
