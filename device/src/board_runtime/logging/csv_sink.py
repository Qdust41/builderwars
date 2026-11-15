"""Local CSV sink: appends the exact log envelopes the runtime sends to a CSV file.

Every ``log`` message the runtime buffers/publishes is also appended to a local CSV
(one row per message, columns mirror the envelope), so the host keeps a debugging copy
even while the cloud link is down. The file is plain UTF-8 CSV; open it in a spreadsheet
or feed it to ``builderwars-logs to-sql``.

The sink is deliberately fail-safe: any I/O error drops the row (with a warning) instead
of propagating into the runtime loop.
"""

from __future__ import annotations

import csv
import logging
import threading
from pathlib import Path
from typing import TextIO

from device_protocol import DeviceEnvelope, MessageType

log = logging.getLogger(__name__)

#: Column order for every CSV file the sink writes (and ``builderwars-logs`` expects).
CSV_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "message_id",
    "schema_version",
    "device_id",
    "sequence_number",
    "firmware_version",
    "hardware_model",
    "level",
    "logger",
    "message",
)


class CsvLogSink:
    """Appends LOG envelopes to a CSV file; I/O errors never propagate to the runtime."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        # RLock: write_envelope() holds the lock while calling open().
        self._lock = threading.RLock()
        self._file: TextIO | None = None

    # -- lifecycle -------------------------------------------------------------------------
    def open(self) -> None:
        """Open in append mode; write the header only for a new/empty file."""
        with self._lock:
            if self._file is not None:
                return
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                is_new = not self.path.exists() or self.path.stat().st_size == 0
                handle = self.path.open("a", encoding="utf-8", newline="")
                if is_new:
                    csv.writer(handle).writerow(CSV_COLUMNS)
                self._file = handle
            except OSError as exc:
                log.warning("csv log sink: cannot open %s: %s", self.path, exc)

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                try:
                    self._file.close()
                except OSError as exc:
                    log.warning("csv log sink: error closing %s: %s", self.path, exc)
                self._file = None

    # -- data ---------------------------------------------------------------------------
    def write_envelope(self, envelope: DeviceEnvelope) -> None:
        """Append one row for a LOG envelope; other message types are ignored."""
        if envelope.message_type is not MessageType.LOG:
            return
        payload = envelope.payload
        row = (
            envelope.timestamp.isoformat(),
            str(envelope.message_id),
            str(envelope.schema_version),
            envelope.device_id,
            "" if envelope.sequence_number is None else str(envelope.sequence_number),
            envelope.firmware_version or "",
            envelope.hardware_model or "",
            str(payload.get("level", "")),
            str(payload.get("logger") or ""),
            str(payload.get("message", "")),
        )
        with self._lock:
            if self._file is None:
                self.open()  # retry once; if it still fails, drop the row
            handle = self._file
            if handle is None:
                return
            try:
                csv.writer(handle).writerow(row)
                handle.flush()
            except (OSError, csv.Error) as exc:
                log.warning("csv log sink: dropping row for %s: %s", self.path, exc)
