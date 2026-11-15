"""Download a device's log history from the Builderwars API and write it as CSV.

``builderwars logs <device>`` pages through ``GET /devices/{id}/logs/history`` as the
signed-in user (any project member may read it) and writes one CSV row per log line or
device event, oldest first. Standard library only (Python 3.10+).
"""

from __future__ import annotations

import csv
import os
import tempfile
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import quote, urlencode

from board_runtime.cloud.account import AccountError, CloudSession

#: Columns of the exported CSV, in order.
CLOUD_LOG_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "device_id",
    "kind",
    "level",
    "message",
    "message_id",
)
#: The API's page size cap for the history endpoint.
PAGE_SIZE = 1000


def iter_log_history(
    session: CloudSession,
    device_id: str,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    page_size: int | None = None,
    on_page: Callable[[int], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield every log/event entry for ``device_id`` (oldest first), following cursors."""
    base = f"/devices/{quote(device_id, safe='')}/logs/history"
    params: dict[str, str] = {"limit": str(page_size or PAGE_SIZE)}
    if since is not None:
        params["since"] = since.isoformat()
    if until is not None:
        params["until"] = until.isoformat()
    total = 0
    seen_cursors: set[str] = set()
    while True:
        page = session.request("GET", f"{base}?{urlencode(params)}")
        if not isinstance(page, dict) or not isinstance(page.get("entries"), list):
            raise AccountError(
                "the API did not return a log history page",
                "the API may be older than this CLI; update it or use the web dashboard",
            )
        entries: list[dict[str, Any]] = page["entries"]
        yield from entries
        total += len(entries)
        if on_page is not None:
            on_page(total)
        cursor = page.get("next_cursor")
        if not cursor:
            return
        if cursor in seen_cursors:  # defensive: never loop forever on a bad server
            raise AccountError("the API returned the same page twice; stopping")
        seen_cursors.add(cursor)
        params["cursor"] = str(cursor)


def write_log_csv(handle: TextIO, device_id: str, entries: Iterator[dict[str, Any]]) -> int:
    """Write the header and one row per entry; return the number of rows."""
    writer = csv.writer(handle)
    writer.writerow(CLOUD_LOG_COLUMNS)
    count = 0
    for entry in entries:
        writer.writerow(
            [
                entry.get("at", ""),
                device_id,
                entry.get("kind", ""),
                entry.get("level", ""),
                entry.get("message", ""),
                entry.get("message_id") or "",
            ]
        )
        count += 1
    return count


def export_logs_csv(
    session: CloudSession,
    device_id: str,
    output: Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    on_page: Callable[[int], None] | None = None,
) -> int:
    """Download the history into ``output`` atomically (a failed download leaves no file)."""
    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".part", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            count = write_log_csv(
                handle,
                device_id,
                iter_log_history(session, device_id, since=since, until=until, on_page=on_page),
            )
        os.replace(tmp_name, output)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return count
