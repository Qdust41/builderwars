"""Hardware access boundary.

Real drivers (GPIO/I2C/SPI/ADC...) depend on the board, which is not chosen yet
(open decision #1). Everything hardware-specific must sit behind ``SensorReader``.
"""

from __future__ import annotations

import math
import random
from typing import Protocol


class SensorReader(Protocol):
    def read(self) -> dict[str, float | int | bool | str]: ...


class SimulatedSensors:
    """Deterministic-ish fake sensors for the simulator and tests. Not real hardware."""

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)  # noqa: S311 - simulation only
        self._tick = 0

    def read(self) -> dict[str, float | int | bool | str]:
        self._tick += 1
        temp = 40.0 + 2.5 * math.sin(self._tick / 5) + self._rng.uniform(-0.2, 0.2)
        return {
            "temperature_c": round(temp, 2),
            "cpu_load_pct": round(self._rng.uniform(5, 60), 1),
            "free_mem_kb": self._rng.randint(20_000, 60_000),
        }
