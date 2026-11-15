"""Full log history paging (``TelemetryRepository.log_history``) on every backend."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from application.adapters import memory
from application.ports import LogPosition
from application.services.telemetry import (
    InvalidLogCursorError,
    decode_log_cursor,
    encode_log_cursor,
)

T0 = datetime(2026, 11, 14, 20, 0, tzinfo=UTC)


@pytest.fixture
def repo(backend: str, request: pytest.FixtureRequest) -> Any:
    if backend == "postgres":
        return request.getfixturevalue("pg").telemetry
    return memory.InMemoryTelemetryRepository()


def _fill(repo: Any) -> None:
    # Two logs and one event share T0+1s: order is (at, logs before events, insertion).
    repo.add_log(device_id="d1", message_id="m0", at=T0, level="info", message="boot")
    repo.add_log(
        device_id="d1", message_id="m1", at=T0 + timedelta(seconds=1), level="info", message="a"
    )
    repo.add_event(
        device_id="d1",
        message_id=None,
        at=T0 + timedelta(seconds=1),
        name="sequence_gap",
        severity="warning",
        detail="3 missing",
    )
    repo.add_log(
        device_id="d1", message_id="m2", at=T0 + timedelta(seconds=1), level="error", message="b"
    )
    repo.add_log(device_id="d2", message_id="x", at=T0, level="info", message="other device")
    repo.add_log(
        device_id="d1", message_id="m3", at=T0 + timedelta(seconds=5), level="info", message="end"
    )


def _page_all(repo: Any, size: int, **kw: Any) -> list[Any]:
    out: list[Any] = []
    after = None
    while True:
        page = repo.log_history("d1", after=after, limit=size, **kw)
        out += page
        if len(page) < size:
            return out
        after = page[-1].position


def test_history_is_ordered_and_scoped_to_the_device(repo: Any) -> None:
    _fill(repo)
    rows = repo.log_history("d1", since=None, until=None, after=None, limit=100)
    assert [(r.kind, r.message, r.message_id) for r in rows] == [
        ("log", "boot", "m0"),
        ("log", "a", "m1"),
        ("log", "b", "m2"),
        ("event", "sequence_gap: 3 missing", None),
        ("log", "end", "m3"),
    ]
    assert rows[3].level == "warning"


@pytest.mark.parametrize("size", [1, 2, 3, 5])
def test_paging_with_ties_on_timestamp_loses_and_repeats_nothing(repo: Any, size: int) -> None:
    _fill(repo)
    paged = _page_all(repo, size, since=None, until=None)
    assert [r.message for r in paged] == ["boot", "a", "b", "sequence_gap: 3 missing", "end"]


def test_time_window_is_since_inclusive_until_exclusive(repo: Any) -> None:
    _fill(repo)
    rows = repo.log_history(
        "d1", since=T0 + timedelta(seconds=1), until=T0 + timedelta(seconds=5), after=None, limit=10
    )
    assert [r.message for r in rows] == ["a", "b", "sequence_gap: 3 missing"]
    assert [r.message for r in _page_all(repo, 1, since=T0 + timedelta(seconds=1), until=None)] == [
        "a",
        "b",
        "sequence_gap: 3 missing",
        "end",
    ]


def test_cursor_round_trip_and_garbage_is_rejected() -> None:
    position = LogPosition(at=T0, source=1, row_id=42)
    assert decode_log_cursor(encode_log_cursor(position)) == position
    for bad in ("nope", "", encode_log_cursor(position)[:-3] + "!!!"):
        with pytest.raises(InvalidLogCursorError):
            decode_log_cursor(bad)
