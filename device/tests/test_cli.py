"""Tests for the builderwars-logs CLI (board_runtime.cli)."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest

from board_runtime.cli import main
from board_runtime.logging import CSV_COLUMNS

NASTY = 'it\'s a "test"\nline two — ünïcode ✓'


def _write_csv(path: Path, messages: list[tuple[str, str, str]]) -> None:
    """messages: list of (level, logger, message); NULLs are empty strings."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for i, (level, logger, message) in enumerate(messages):
            writer.writerow(
                [
                    "2026-11-14T12:00:00+00:00",
                    f"00000000-0000-4000-8000-{i:012d}",
                    "1",
                    "dev-test-001",
                    "" if i % 2 else str(i),
                    "1.2.3",
                    "freewili-1-og",
                    level,
                    logger,
                    message,
                ]
            )


def _sql_roundtrip(sql: str) -> list[tuple]:
    con = sqlite3.connect(":memory:")
    con.executescript(sql)
    rows = con.execute(
        "SELECT message_id, schema_version, device_id, timestamp, sequence_number, "
        "firmware_version, hardware_model, level, logger, message FROM host_device_logs"
        " ORDER BY message_id"
    ).fetchall()
    con.close()
    return rows


def test_to_sql_writes_executable_dump_with_escaping(tmp_path: Path) -> None:
    csv_path = tmp_path / "dev.csv"
    out = tmp_path / "upload.sql"
    _write_csv(
        csv_path,
        [
            ("info", "app", "plain message"),
            ("warning", "", NASTY),  # NULL logger + quotes/newline/unicode
            ("error", "app", "semi;colon AND 'single' and \"double\""),
        ],
    )
    assert main(["to-sql", str(csv_path), "-o", str(out), "--yes"]) == 0
    sql = out.read_text(encoding="utf-8")

    rows = _sql_roundtrip(sql)
    assert len(rows) == 3
    by_message = {row[9]: row for row in rows}
    assert by_message[NASTY][8] is None  # blank logger -> NULL
    assert by_message["plain message"][4] == "0"
    assert by_message[NASTY][4] is None  # blank sequence -> NULL
    assert by_message["semi;colon AND 'single' and \"double\""][7] == "error"
    assert "BEGIN;" in sql
    assert sql.rstrip().endswith("COMMIT;")
    assert sql.count("CREATE TABLE IF NOT EXISTS host_device_logs") == 1


def test_to_sql_prompt_no_skips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_path = tmp_path / "dev.csv"
    _write_csv(csv_path, [("info", "app", "hi")])
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert main(["to-sql", str(csv_path)]) == 0
    assert not csv_path.with_suffix(".sql").exists()


def test_to_sql_prompt_blank_defaults_to_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "dev.csv"
    _write_csv(csv_path, [("info", "app", "hi")])
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    assert main(["to-sql", str(csv_path)]) == 0
    assert csv_path.with_suffix(".sql").exists()


def test_to_sql_prompt_eof_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    csv_path = tmp_path / "dev.csv"
    _write_csv(csv_path, [("info", "app", "hi")])

    def _eof(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)
    assert main(["to-sql", str(csv_path)]) == 1
    assert "--yes" in capsys.readouterr().err


def test_to_sql_resolves_device_id_under_logs_dir(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()
    _write_csv(tmp_path / "logs" / "sim-001.csv", [("info", "app", "hi")])
    assert main(["--state-dir", str(tmp_path), "to-sql", "sim-001", "--yes"]) == 0
    assert (tmp_path / "logs" / "sim-001.sql").exists()


def test_to_sql_missing_file_returns_2(tmp_path: Path) -> None:
    assert main(["--state-dir", str(tmp_path), "to-sql", "nope.csv"]) == 2


def test_to_sql_rejects_wrong_header(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    assert main(["to-sql", str(csv_path), "--yes"]) == 2


def test_to_sql_empty_file_is_an_error(tmp_path: Path) -> None:
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("", encoding="utf-8")
    assert main(["to-sql", str(csv_path), "--yes"]) == 2


def test_show_lists_csv_files(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    (tmp_path / "logs").mkdir()
    _write_csv(tmp_path / "logs" / "sim-001.csv", [("info", "app", "hi")])
    assert main(["--state-dir", str(tmp_path), "show"]) == 0
    out = capsys.readouterr().out
    assert "sim-001.csv" in out
    assert "rows=1" in out


def test_show_empty_dir(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["--state-dir", str(tmp_path), "show"]) == 0
    assert "No log CSVs" in capsys.readouterr().out


def test_to_sql_dump_never_touches_the_cloud_device_logs_table(tmp_path: Path) -> None:
    """The cloud DB already has a differently shaped ``device_logs``; the dump must not hit it."""
    csv_path = tmp_path / "dev.csv"
    out = tmp_path / "upload.sql"
    _write_csv(csv_path, [("info", "app", "one"), ("error", "app", "two")])
    assert main(["to-sql", str(csv_path), "-o", str(out), "--yes"]) == 0
    sql = out.read_text(encoding="utf-8")

    con = sqlite3.connect(":memory:")
    con.execute(  # shape of the PostgreSQL migration's table
        "CREATE TABLE device_logs (id INTEGER PRIMARY KEY, device_id TEXT NOT NULL,"
        " message_id TEXT NOT NULL, at TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL)"
    )
    con.executescript(sql)
    con.executescript(sql)  # loading the same dump twice skips rows already present
    assert con.execute("SELECT count(*) FROM device_logs").fetchone() == (0,)
    assert con.execute("SELECT count(*) FROM host_device_logs").fetchone() == (2,)
    con.close()


def test_sim_respects_log_csv_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("BUILDERWARS_LOG_CSV", "off")
    assert main(["--state-dir", str(tmp_path), "sim", "--count", "1"]) == 0
    assert not (tmp_path / "logs").exists()
    assert "also written" not in capsys.readouterr().err


def test_sim_writes_csv_under_state_dir_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BUILDERWARS_LOG_CSV", raising=False)
    assert main(["--state-dir", str(tmp_path), "sim", "--count", "1"]) == 0
    assert (tmp_path / "logs" / "sim-001.csv").is_file()


def test_run_over_mqtt_requires_a_real_device_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv("DEVICE_ID", raising=False)
    monkeypatch.setenv("DEVICE_TRANSPORT", "mqtt")
    assert main(["--state-dir", str(tmp_path), "run", "-n", "1"]) == 2
    assert "registered device id" in capsys.readouterr().err
