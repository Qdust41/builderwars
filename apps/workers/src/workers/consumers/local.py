"""Local harness: feed simulator output (JSON lines) through the real ingest pipeline."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TextIO

from application.services import IngestOutcome, IngestResult
from workers.handlers.device_message import DeviceMessageHandler, IncomingDeviceMessage


def read_jsonl(stream: TextIO) -> Iterator[IncomingDeviceMessage]:
    """Each line: ``{"topic": ..., "payload": <envelope object or raw string>}``."""
    for line in stream:
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        payload = item["payload"]
        body = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
        yield IncomingDeviceMessage.from_raw(item["topic"], body, datetime.now(UTC))


@dataclass
class LocalHarness:
    handler: DeviceMessageHandler
    results: list[IngestResult] = field(default_factory=list)

    def run(self, messages: Iterable[IncomingDeviceMessage]) -> Counter[IngestOutcome]:
        counts: Counter[IngestOutcome] = Counter()
        for message in messages:
            result = self.handler.handle(message)
            self.results.append(result)
            counts[result.outcome] += 1
        return counts
