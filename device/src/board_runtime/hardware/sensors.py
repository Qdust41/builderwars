"""Hardware access boundary. Everything board-specific sits behind ``SensorReader``."""

from __future__ import annotations

import math
import random
from typing import Protocol

from device_protocol.schemas import MetricValue


class BoardUnavailableError(Exception):
    """The board can't be reached (e.g. USB unplugged). The runtime reports ``degraded``."""


class SensorReader(Protocol):
    def read(self) -> dict[str, MetricValue]:
        """Return one sample of readings, or raise ``BoardUnavailableError``."""
        ...


class SimulatedSensors:
    """Deterministic-ish fake sensors for the simulator and tests. Not real hardware."""

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)  # noqa: S311 - simulation only
        self._tick = 0

    def read(self) -> dict[str, MetricValue]:
        self._tick += 1
        temp = 40.0 + 2.5 * math.sin(self._tick / 5) + self._rng.uniform(-0.2, 0.2)
        return {
            "temperature_c": round(temp, 2),
            "cpu_load_pct": round(self._rng.uniform(5, 60), 1),
            "free_mem_kb": self._rng.randint(20_000, 60_000),
        }
