from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    """Exponential backoff with full jitter for reconnects.

    Placeholder values; tune once real network conditions are known.
    """

    base_s: float = 1.0
    max_s: float = 300.0
    multiplier: float = 2.0

    def ceiling(self, attempt: int) -> float:
        if attempt < 0:
            raise ValueError("attempt must be >= 0")
        return float(min(self.max_s, self.base_s * self.multiplier**attempt))

    def delay(self, attempt: int, rng: random.Random | None = None) -> float:
        return (rng or random).uniform(0, self.ceiling(attempt))
