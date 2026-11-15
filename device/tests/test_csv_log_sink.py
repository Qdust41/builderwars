"""Tests for the local CSV log sink (board_runtime.logging.csv_sink)."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from board_runtime.logging import CSV_COLUMNS, CsvLogSink
from device_protocol import DeviceEnvelope, MessageType
from device_protocol.compat import UTC

TS = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)


def _log_envelope(
    *,
    message: str = "hello world",
    logger: str | None = "app.logger",
    level: str = "info",
    sequence: int | None = 7,
    firmware: str | None = "0.0.0-sim",
) -> DeviceEnvelope:
    return DeviceEnvelope.new(
        device_id="dev-test-001",
        message_type=MessageType.LOG,
        payload={"level": level, "message": message, "logger": logger},
        sequence_number=sequence,
        firmware_version=firmware,
        hardware_model="freewili-1-og",
        timestamp=TS,
    )


def _read_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [row for row in csv.reader(handle)]


def test_header_written_once_and_rows_append_across_reopens(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "dev.csv"
    sink = CsvLogSink(path)
    sink.write_envelope(_log_envelope(message="first"))
    sink.close()
    # Reopen: header must not be duplicated.
    sink2 = CsvLogSink(path)
    sink2.write_envelope(_log_envelope(message="second"))
    sink2.close()

    rows = _read_rows(path)
    assert rows[0] == list(CSV_COLUMNS)
    assert [row[9] for row in rows[1:]] == ["first", "second"]


def test_row_matches_envelope_fields(tmp_path: Path) -> None:
    path = tmp_path / "dev.csv"
    sink = CsvLogSink(path)
    env = _log_envelope(
        message='it\'s a "test"\nwith a newline',
        level="warning",
        sequence=42,
        firmware="1.2.3",
    )
    sink.write_envelope(env)
    sink.close()

    rows = _read_rows(path)
    row = dict(zip(CSV_COLUMNS, rows[1], strict=True))
    assert row["timestamp"] == TS.isoformat()
    assert row["message_id"] == str(env.message_id)
    assert row["device_id"] == "dev-test-001"
    assert row["sequence_number"] == "42"
    assert row["firmware_version"] == "1.2.3"
    assert row["hardware_model"] == "freewili-1-og"
    assert row["level"] == "warning"
    assert row["logger"] == "app.logger"
    assert row["message"] == 'it\'s a "test"\nwith a newline'


def test_optional_fields_become_blank_strings(tmp_path: Path) -> None:
    path = tmp_path / "dev.csv"
    sink = CsvLogSink(path)
    sink.write_envelope(_log_envelope(sequence=None, logger=None, firmware=None))
    sink.close()

    row = dict(zip(CSV_COLUMNS, _read_rows(path)[1], strict=True))
    assert row["sequence_number"] == ""
    assert row["logger"] == ""
    assert row["firmware_version"] == ""


def test_non_log_envelopes_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "dev.csv"
    sink = CsvLogSink(path)
    heartbeat = DeviceEnvelope.new(
        device_id="dev-test-001",
        message_type=MessageType.HEARTBEAT,
        payload={"uptime_s": 3},
        timestamp=TS,
    )
    sink.write_envelope(heartbeat)
    sink.write_envelope(_log_envelope(message="kept"))
    sink.close()

    rows = _read_rows(path)
    assert len(rows) == 2  # header + one log row


def test_io_errors_never_propagate(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    sink = CsvLogSink(blocker / "sub" / "dev.csv")
    sink.write_envelope(_log_envelope())  # open() fails -> row dropped, no exception
    sink.close()
    assert not blocker.joinpath("sub").exists()
