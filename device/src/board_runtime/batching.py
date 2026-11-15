"""Host-side telemetry batching (decision #6): flush every window, at the sample cap, or
before the payload would outgrow the envelope's size limit (wide samples, e.g. 40+ readings
from ``run --logger real``, hit 16 KB well before 32 samples)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from device_protocol.envelopes import MAX_PAYLOAD_BYTES
from device_protocol.schemas import MetricValue

# Room left for '{"samples":[...]}' and separators, with a margin.
_HEADROOM_BYTES = 512


def _size(sample: dict[str, Any]) -> int:
    return len(json.dumps(sample, separators=(",", ":")).encode()) + 1  # + the comma


class TelemetryBatcher:
    def __init__(
        self,
        *,
        window_s: float,
        max_samples: int,
        max_bytes: int = MAX_PAYLOAD_BYTES - _HEADROOM_BYTES,
    ) -> None:
        self._window_s = window_s
        self._max = max_samples
        self._max_bytes = max_bytes
        self._samples: list[dict[str, Any]] = []
        self._bytes = 0
        self._window_started: float | None = None

    def __len__(self) -> int:
        return len(self._samples)

    def add(
        self, readings: dict[str, MetricValue], *, at: datetime, now: float
    ) -> dict[str, Any] | None:
        """Add a sample; return a payload when the batch is full, else None.

        If this sample would push the batch past ``max_bytes``, the batch so far is returned
        and this sample starts the next one."""
        sample = {"ts": at.isoformat(), "readings": dict(readings)}
        size = _size(sample)
        full: dict[str, Any] | None = None
        if self._samples and self._bytes + size > self._max_bytes:
            full = self.flush()
        if self._window_started is None:
            self._window_started = now
        self._samples.append(sample)
        self._bytes += size
        if full is None and len(self._samples) >= self._max:
            return self.flush()
        return full

    def due(self, now: float) -> bool:
        return self._window_started is not None and now - self._window_started >= self._window_s

    def flush(self) -> dict[str, Any] | None:
        if not self._samples:
            return None
        payload = {"samples": self._samples}
        self._samples = []
        self._bytes = 0
        self._window_started = None
        return payload
