"""Small compatibility shims so the protocol (and the host runtime) run on CPython 3.10+.

The board runtime runs on the host PC next to the FREE-WILi, which may only have Python 3.10
(decision #1). Cloud code targets 3.12 but shares this package, so it must stay 3.10-safe:
no ``enum.StrEnum``, no ``datetime.UTC``, no ``typing.Self``.
"""

from __future__ import annotations

import sys
from datetime import timezone
from enum import Enum

UTC = timezone.utc

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:  # pragma: no cover - exercised by the Python 3.10 CI job

    class StrEnum(str, Enum):
        """Backport of 3.11's StrEnum: members are strings and str() gives the value."""

        def __str__(self) -> str:
            return str(self.value)


__all__ = ["UTC", "StrEnum"]
