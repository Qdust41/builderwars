"""``builderwars-logs`` — inspect local device log CSVs and build upload-ready SQL dumps.

The device runtime and simulator append every log message they send to the cloud to a
local CSV file under ``~/.builderwars/logs/<device-id>.csv`` (override with
``BUILDERWARS_LOG_CSV``). This CLI turns those files into a self-contained ``.sql`` dump
you can execute in PostgreSQL (or SQLite) for upload.

    builderwars-logs show                       # list CSV files under the state dir
    builderwars-logs to-sql sim-001             # asks [Y/n], writes sim-001.sql next to it
    builderwars-logs to-sql /path/logs.csv -o /tmp/upload.sql --yes
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from board_runtime.config import default_state_dir
from board_runtime.logging import CSV_COLUMNS

#: Columns that may be NULL when empty (everything else is required by the sink).
_NULLABLE = frozenset({"sequence_number", "firmware_version", "hardware_model", "logger"})

#: SQL column order — kept identical to CSV_COLUMNS so value order always matches the
#: INSERT column list (a mismatch would silently swap values between columns).
SQL_COLUMNS: tuple[str, ...] = CSV_COLUMNS

_TABLE_DDL = """\
CREATE TABLE IF NOT EXISTS device_logs (
    timestamp TEXT NOT NULL,
    message_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    device_id TEXT NOT NULL,
    sequence_number TEXT,
    firmware_version TEXT,
    hardware_model TEXT,
    level TEXT NOT NULL,
    logger TEXT,
    message TEXT NOT NULL
);"""

_INSERT_HEADER = (
    f"INSERT INTO device_logs ({', '.join(SQL_COLUMNS)}) VALUES "
)


# -- helpers -----------------------------------------------------------------------------
def _logs_dir(state_dir: Path) -> Path:
    return Path(state_dir) / "logs"


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_value(column: str, value: str) -> str:
    if value == "" and column in _NULLABLE:
        return "NULL"
    return _sql_text(value)


def read_log_csv(path: Path) -> list[dict[str, str]]:
    """Read one sink CSV; raise ``ValueError`` if the header is not the sink's shape."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames
        if header is None:
            raise ValueError(f"{path}: file is empty (no header row)")
        if tuple(header) != CSV_COLUMNS:
            raise ValueError(
                f"{path}: unexpected header {header!r}; expected {list(CSV_COLUMNS)!r} "
                "(is this a CSV written by the board runtime sink?)"
            )
        return [
            {column: (row[column] or "") for column in CSV_COLUMNS}
            for row in reader
            if any((row[column] or "") for column in CSV_COLUMNS)
        ]


def render_sql(source: Path, rows: list[dict[str, str]]) -> str:
    """Render the self-contained dump: BEGIN + CREATE TABLE + INSERTs + COMMIT."""
    lines = [
        "-- builderwars device log dump",
        f"-- source: {source}",
        f"-- rows: {len(rows)}",
        f"-- generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "-- Load with:  psql -f <this file>   (or: sqlite3 <db> <this file>)",
        "BEGIN;",
        _TABLE_DDL,
    ]
    for row in rows:
        values = ", ".join(_sql_value(column, row[column]) for column in SQL_COLUMNS)
        lines.append(f"{_INSERT_HEADER}({values});")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


# -- commands ------------------------------------------------------------------------------
def cmd_show(args: argparse.Namespace) -> int:
    logs_dir = _logs_dir(args.state_dir)
    files = sorted(logs_dir.glob("*.csv")) if logs_dir.is_dir() else []
    if not files:
        print(f"No log CSVs found in {logs_dir}.")
        print(
            "The runtime writes them automatically (set BUILDERWARS_LOG_CSV=off to disable)."
        )
        return 0
    for path in files:
        try:
            rows = read_log_csv(path)
            count, err = len(rows), None
        except (OSError, ValueError) as exc:
            count, err = 0, str(exc)
        mtime = datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(
            timespec="seconds"
        )
        print(f"{path}  rows={count}  size={path.stat().st_size} B  last-write={mtime}")
        if err:
            print(f"  ! {err}")
    return 0


def cmd_to_sql(args: argparse.Namespace) -> int:
    state_dir: Path = args.state_dir
    csv_path = Path(args.csv).expanduser()
    if not csv_path.is_file():
        candidate = _logs_dir(state_dir) / f"{csv_path.name}.csv"
        if candidate.is_file():
            csv_path = candidate
        else:
            print(f"error: log CSV not found: {args.csv}", file=sys.stderr)
            print(f"(also tried {candidate})", file=sys.stderr)
            return 2
    try:
        rows = read_log_csv(csv_path)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not args.yes:
        try:
            answer = input(f"Parse {csv_path.name} into SQL-compatible data for upload? [Y/n] ")
        except EOFError:
            print("\nerror: no answer (stdin closed); re-run with --yes to skip the prompt", file=sys.stderr)
            return 1
        if answer.strip().lower() in {"n", "no"}:
            print(f"Skipped — {csv_path} left unchanged.")
            return 0

    out_path = Path(args.output).expanduser() if args.output else csv_path.with_suffix(".sql")
    out_path.write_text(render_sql(csv_path, rows), encoding="utf-8")
    print(f"Wrote {out_path} ({len(rows)} rows).")
    return 0


# -- entry point ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="builderwars-logs",
        description="Inspect local device log CSVs and convert them to SQL-compatible dumps.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=default_state_dir(),
        help="state dir holding the logs/ folder (default: ~/.builderwars)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_show = sub.add_parser("show", help="list stored log CSVs with row counts")
    p_show.set_defaults(func=cmd_show)

    p_sql = sub.add_parser(
        "to-sql", help="convert one log CSV into a self-contained .sql dump (asks [Y/n])"
    )
    p_sql.add_argument("csv", help="CSV path, or a device id (looked up under <state-dir>/logs)")
    p_sql.add_argument("-o", "--output", help="output .sql path (default: <csv>.sql next to it)")
    p_sql.add_argument("--yes", action="store_true", help="skip the [Y/n] prompt")
    p_sql.set_defaults(func=cmd_to_sql)

    args: Any = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
