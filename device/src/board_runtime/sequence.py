"""Per-device message sequence numbers, persisted across host reboots (decision #14).

A gap in ``sequence_number`` then means "messages were lost", not "the host restarted".
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol


class SequenceStore(Protocol):
    def next(self) -> int:
        """Reserve and return the next sequence number."""
        ...


class MemorySequenceStore:
    """Non-persistent counter for tests and the simulator."""

    def __init__(self, start: int = 0) -> None:
        self._next = start

    def next(self) -> int:
        value = self._next
        self._next += 1
        return value


class FileSequenceStore:
    """Stores the next sequence number in ``<state_dir>/seq/<device_id>``.

    The number is persisted *before* it is handed out (atomic temp-file + rename), so a crash
    can only skip a number, never reuse one.
    """

    def __init__(self, state_dir: Path, device_id: str) -> None:
        self._path = state_dir / "seq" / device_id
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._next = self._load()

    def _load(self) -> int:
        try:
            value = int(self._path.read_text(encoding="ascii").strip())
        except FileNotFoundError:
            return 0
        except ValueError as exc:
            raise RuntimeError(f"corrupt sequence file {self._path}") from exc
        if value < 0:
            raise RuntimeError(f"corrupt sequence file {self._path}")
        return value

    def next(self) -> int:
        value = self._next
        self._write(value + 1)
        self._next = value + 1
        return value

    def _write(self, value: int) -> None:
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".seq-")
        try:
            with os.fdopen(fd, "w", encoding="ascii") as fh:
                fh.write(str(value))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
