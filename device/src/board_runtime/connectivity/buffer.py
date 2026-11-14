from __future__ import annotations

from collections import deque
from typing import Protocol


class OfflineBuffer(Protocol):
    """Holds outgoing messages while disconnected.

    TODO: a persistent implementation (flash/SD) if messages must survive reboots — depends on
    board storage (open decision #1).
    """

    def append(self, topic: str, payload: bytes) -> None: ...
    def peek(self) -> tuple[str, bytes] | None: ...
    def pop(self) -> tuple[str, bytes] | None: ...
    def __len__(self) -> int: ...


class BoundedMemoryBuffer:
    """FIFO in RAM; when full, drops the OLDEST message and counts the drop."""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._items: deque[tuple[str, bytes]] = deque()
        self._capacity = capacity
        self.dropped = 0

    def append(self, topic: str, payload: bytes) -> None:
        if len(self._items) >= self._capacity:
            self._items.popleft()
            self.dropped += 1
        self._items.append((topic, payload))

    def peek(self) -> tuple[str, bytes] | None:
        return self._items[0] if self._items else None

    def pop(self) -> tuple[str, bytes] | None:
        return self._items.popleft() if self._items else None

    def __len__(self) -> int:
        return len(self._items)
