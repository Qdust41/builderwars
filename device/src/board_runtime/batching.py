"""Host-side telemetry batching (decision #6): flush every window or at the sample cap."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from device_protocol.schemas import MetricValue


class TelemetryBatcher:
    def __init__(self, *, window_s: float, max_samples: int) -> None:
        self._window_s = window_s
        self._max = max_samples
        self._samples: list[dict[str, Any]] = []
        self._window_started: float | None = None

    def __len__(self) -> int:
        return len(self._samples)

    def add(
        self, readings: dict[str, MetricValue], *, at: datetime, now: float
    ) -> dict[str, Any] | None:
        """Add a sample; return a payload when the batch is full, else None."""
        if self._window_started is None:
            self._window_started = now
        self._samples.append({"ts": at.isoformat(), "readings": dict(readings)})
        if len(self._samples) >= self._max:
            return self.flush()
        return None

    def due(self, now: float) -> bool:
        return self._window_started is not None and now - self._window_started >= self._window_s

    def flush(self) -> dict[str, Any] | None:
        if not self._samples:
            return None
        payload = {"samples": self._samples}
        self._samples = []
        self._window_started = None
        return payload
