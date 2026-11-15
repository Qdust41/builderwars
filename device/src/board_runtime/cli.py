"""``builderwars`` — test a FREE-WILi board, run the host runtime, and manage local logs.

    builderwars                         # list FREE-WILi boards / serial ports, show next steps
    builderwars /dev/ttyACM0            # test that board (same as: builderwars test /dev/ttyACM0)
    builderwars test --watch            # first board found; print GPIO/button changes live
    builderwars ports                   # list boards and serial ports with permission status
    builderwars run /dev/ttyACM0        # full host runtime on that board, messages to stdout
    builderwars sim --count 40          # simulated board, messages to stdout
    builderwars show                    # list stored log CSVs (alias: logs)
    builderwars to-sql sim-001          # asks [Y/n], writes sim-001.sql next to the CSV

The device runtime and simulator append every log message they send to the cloud to a local
CSV under ``~/.builderwars/logs/<device-id>.csv`` (override with ``BUILDERWARS_LOG_CSV``);
``to-sql`` turns one into a self-contained ``.sql`` dump for PostgreSQL or SQLite.

Exit codes: 0 ok, 1 board test failed, 2 usage/setup error, 130 interrupted.
``builderwars-logs`` is the same program (kept for compatibility).
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from board_runtime.config import (
    ConfigError,
    DeviceConfig,
    SensorKind,
    TransportKind,
    default_state_dir,
    log_csv_path_from_env,
)
from board_runtime.hardware.freewili import (
    BoardInfo,
    FreeWiliNotInstalledError,
    FreeWiliSensors,
    close_quietly,
    find_boards,
    import_freewili,
    select_board,
)
from board_runtime.hardware.ports import (
    PortProblem,
    check_port,
    list_ports,
    open_error_hint,
    permission_hint,
    same_port,
)
from board_runtime.hardware.sensors import BoardUnavailableError
from board_runtime.logging import CSV_COLUMNS

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130

#: Columns that may be NULL when empty (everything else is required by the sink).
_NULLABLE = frozenset({"sequence_number", "firmware_version", "hardware_model", "logger"})

#: SQL column order — kept identical to CSV_COLUMNS so value order always matches the
#: INSERT column list (a mismatch would silently swap values between columns).
SQL_COLUMNS: tuple[str, ...] = CSV_COLUMNS

#: Table the dump creates. Deliberately NOT ``device_logs``: the cloud database already has a
#: ``device_logs`` table with a different shape (PostgreSQL migration 0001), so a dump loaded
#: there would fail. Rows here are a staging copy; the upload path in
#: docs/log-ingestion-spec.md maps them into the canonical table.
DUMP_TABLE = "host_device_logs"

_TABLE_DDL = f"""\
CREATE TABLE IF NOT EXISTS {DUMP_TABLE} (
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

_INSERT_HEADER = f"INSERT INTO {DUMP_TABLE} ({', '.join(SQL_COLUMNS)}) VALUES "  # noqa: S608
#: Re-loading the same dump (or two dumps that overlap) skips rows already present.
#: ``ON CONFLICT ... DO NOTHING`` works in PostgreSQL 9.5+ and SQLite 3.24+.
_INSERT_TRAILER = " ON CONFLICT (message_id) DO NOTHING;"


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
        f"-- Creates/fills {DUMP_TABLE}; it never touches the cloud's device_logs table.",
        "BEGIN;",
        _TABLE_DDL,
    ]
    for row in rows:
        values = ", ".join(_sql_value(column, row[column]) for column in SQL_COLUMNS)
        lines.append(f"{_INSERT_HEADER}({values}){_INSERT_TRAILER}")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


# -- commands ------------------------------------------------------------------------------
def cmd_show(args: argparse.Namespace) -> int:
    logs_dir = _logs_dir(args.state_dir)
    files = sorted(logs_dir.glob("*.csv")) if logs_dir.is_dir() else []
    if not files:
        print(f"No log CSVs found in {logs_dir}.")
        print("The runtime writes them automatically (set BUILDERWARS_LOG_CSV=off to disable).")
        return 0
    for path in files:
        try:
            rows = read_log_csv(path)
            count, err = len(rows), None
        except (OSError, ValueError) as exc:
            count, err = 0, str(exc)
        mtime = (
            datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
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
            print(
                "\nerror: no answer (stdin closed); re-run with --yes to skip the prompt",
                file=sys.stderr,
            )
            return 1
        if answer.strip().lower() in {"n", "no"}:
            print(f"Skipped — {csv_path} left unchanged.")
            return 0

    out_path = Path(args.output).expanduser() if args.output else csv_path.with_suffix(".sql")
    out_path.write_text(render_sql(csv_path, rows), encoding="utf-8")
    print(f"Wrote {out_path} ({len(rows)} rows).")
    return 0


# -- terminal output -----------------------------------------------------------------------
def _unicode_ok() -> bool:
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
    return "utf" in encoding


class Report:
    """Checklist-style output: ``✓ step`` / ``✗ step`` + indented fix hints."""

    def __init__(self) -> None:
        uni = _unicode_ok()
        self.good = "✓" if uni else "ok"
        self.bad = "✗" if uni else "!!"

    def ok(self, message: str) -> None:
        print(f"  {self.good} {message}", flush=True)

    def info(self, message: str) -> None:
        print(f"    {message}", flush=True)

    def fail(self, message: str, hint: str | None = None) -> int:
        print(f"  {self.bad} {message}", flush=True)
        for line in (hint or "").splitlines():
            print(f"      {line}", flush=True)
        print("FAIL", flush=True)
        return EXIT_FAILED


def _error(message: str, hint: str | None = None) -> None:
    print(f"error: {message}", file=sys.stderr)
    for line in (hint or "").splitlines():
        print(f"  {line}", file=sys.stderr)


def normalize_port(port: str | None) -> str | None:
    """Accept ``ttyACM0`` for ``/dev/ttyACM0``; leave everything else alone."""
    if not port or os.name != "posix" or port.startswith("/"):
        return port
    if port.startswith(("tty", "cu.")) or os.path.exists(f"/dev/{port}"):
        return f"/dev/{port}"
    return port


def _looks_like_port(token: str) -> bool:
    lowered = token.lower()
    return token.startswith(("/", "tty", "cu.")) or (
        lowered.startswith("com") and lowered[3:].isdigit()
    )


def format_readings(readings: dict[str, Any], previous: dict[str, Any] | None = None) -> str:
    """One compact line: GPIO levels as grouped bits, pressed buttons, anything else, changes."""
    io = sorted(
        (int(key[3:]), int(value))
        for key, value in readings.items()
        if key.startswith("io_") and key[3:].isdigit()
    )
    parts: list[str] = []
    if io:
        bits = "".join(str(level) for _, level in io)
        grouped = " ".join(bits[i : i + 8] for i in range(0, len(bits), 8))
        parts.append(f"GPIO[0-{len(io) - 1}] {grouped}")
    buttons = {k[7:]: v for k, v in readings.items() if k.startswith("button_")}
    if buttons:
        pressed = [name for name, down in buttons.items() if down]
        parts.append("buttons: " + (", ".join(pressed) + " pressed" if pressed else "none pressed"))
    for key, value in readings.items():
        if not key.startswith(("io_", "button_")):
            parts.append(f"{key}={value}")
    if previous is not None:
        changed = [
            f"{key} {previous.get(key)}->{value}"
            for key, value in readings.items()
            if previous.get(key) != value
        ]
        if changed:
            parts.append("changed: " + ", ".join(changed))
    return "  ".join(parts)


# -- board commands ---------------------------------------------------------------------------
def _freewili_version() -> str:
    try:
        from importlib.metadata import version

        return version("freewili")
    except Exception:
        return "?"


def cmd_test(args: argparse.Namespace) -> int:
    """Step-by-step board check. Each step either passes or stops with a cause and a fix."""
    port = normalize_port(args.port)
    report = Report()
    print(f"Testing FREE-WILi on {port}" if port else "Testing the first FREE-WILi found on USB")

    if port:
        try:
            check_port(port)
        except PortProblem as problem:
            return report.fail(problem.message, problem.hint)
        if port.startswith("/"):
            report.ok(f"{port} is a serial device you can read and write")

    try:
        freewili, _ = import_freewili()
    except FreeWiliNotInstalledError as exc:
        return report.fail("the 'freewili' Python package is not installed", exc.hint)
    report.ok(f"freewili package {_freewili_version()} is installed")

    try:
        info, board = select_board(port, freewili)
    except BoardUnavailableError as exc:
        return report.fail(str(exc), exc.hint)
    report.ok(f"found {info.describe()}")
    if port and same_port(port, info.display_port):
        report.info("(that is the display CPU's port; the whole board will be tested)")

    for other in info.ports:
        if same_port(other, port):
            continue
        try:
            check_port(other)
        except PortProblem as problem:
            return report.fail(f"the board's other port: {problem.message}", problem.hint)

    started = time.monotonic()
    opened = board.open(True, float(args.timeout))
    if opened.is_err():
        error = str(opened.unwrap_err())
        close_quietly(board)
        return report.fail(
            f"could not open the board's serial ports: {error}",
            open_error_hint(port or info.main_port, error),
        )
    report.ok(f"opened the serial connection in {time.monotonic() - started:.1f} s")

    sensors = FreeWiliSensors.adopt(board, info, port=port)
    try:
        return _sample(report, sensors, args)
    finally:
        sensors.close()


def _sample(report: Report, sensors: FreeWiliSensors, args: argparse.Namespace) -> int:
    previous: dict[str, Any] | None = None
    count = 0
    if args.watch:
        print("Watching for GPIO/button changes; press a button on the board. Ctrl+C to stop.")
    try:
        while args.watch or count < args.samples:
            try:
                readings = sensors.read()
            except BoardUnavailableError as exc:
                return report.fail(f"read #{count + 1} failed: {exc}", exc.hint)
            count += 1
            if not args.watch or previous is None or readings != previous:
                print(f"    #{count:<3} {format_readings(readings, previous)}", flush=True)
            previous = readings
            if args.watch or count < args.samples:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print()
        if count == 0:
            raise
    report.ok(f"{count} read{'s' if count != 1 else ''} from the board succeeded")
    print("PASS")
    return EXIT_OK


def _role(path: str, boards: list[BoardInfo]) -> str:
    for info in boards:
        if same_port(path, info.main_port):
            return f"FREE-WILi main CPU (serial {info.serial})"
        if same_port(path, info.display_port):
            return f"FREE-WILi display CPU (serial {info.serial})"
    return ""


def _print_ports() -> tuple[list[BoardInfo], list[str]]:
    """Print boards + serial ports. Returns (boards, ports you can't access)."""
    boards: list[BoardInfo] = []
    try:
        boards = [info for info, _ in find_boards()]
    except FreeWiliNotInstalledError as exc:
        print(f"FREE-WILi detection unavailable: freewili is not installed ({exc.hint})")
    except BoardUnavailableError as exc:
        print(f"FREE-WILi detection failed: {exc}")
    else:
        if boards:
            print("FREE-WILi boards:")
            for info in boards:
                print(f"  {info.describe()}")
        else:
            print("FREE-WILi boards: none found")

    ports = list_ports()
    no_access: list[str] = []
    if ports:
        print("Serial ports:")
        for status in ports:
            access = "ok" if status.accessible else "NO ACCESS"
            role = _role(status.path, boards)
            alias = f"  ({status.alias})" if status.alias else ""
            print(f"  {status.path:<14} {access:<9} {role}{alias}".rstrip())
            if not status.accessible:
                no_access.append(status.path)
    elif os.name == "posix":
        print("Serial ports: none (is the board plugged in? some USB cables are charge-only)")
    return boards, no_access


def cmd_ports(args: argparse.Namespace) -> int:
    _, no_access = _print_ports()
    if no_access:
        print()
        print("You can't open " + ", ".join(no_access) + ":")
        for line in permission_hint(no_access[0]).splitlines()[1:]:
            print(f"  {line}")
    return EXIT_OK


def cmd_home(args: argparse.Namespace) -> int:
    """What bare ``builderwars`` does: show what is plugged in and what to type next."""
    boards, no_access = _print_ports()
    print()
    first = next((b.main_port for b in boards if b.main_port), None)
    if first is None:
        first = next((p.path for p in list_ports()), "/dev/ttyACM0")
    rows = [
        (f"builderwars {first}", "test that board"),
        ("builderwars test --watch", "live GPIO/button changes on the first board"),
        (f"builderwars run {first}", "full host runtime on that board"),
        ("builderwars --help", "every command"),
    ]
    width = max(len(command) for command, _ in rows) + 3
    print("Next:")
    for command, what in rows:
        print(f"  {command:<{width}}{what}")
    if no_access:
        print()
        print(
            "Note: you can't open "
            + ", ".join(no_access)
            + "; `builderwars ports` says how to fix it."
        )
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    port = normalize_port(args.port)
    env = dict(os.environ)
    env.setdefault("BUILDERWARS_STATE_DIR", str(args.state_dir))
    if port:
        env["DEVICE_PORT"] = port
    device_id = args.device_id or env.get("DEVICE_ID")
    if not device_id and (env.get("DEVICE_TRANSPORT") or "").strip().lower() == TransportKind.MQTT:
        # AWS IoT only accepts a certificate as its own thing, so a made-up id can't connect.
        _error(
            "DEVICE_TRANSPORT=mqtt needs the registered device id",
            "pass --device-id dev_... or set DEVICE_ID (the id the web app shows for the device;\n"
            "it is also the AWS IoT thing name)",
        )
        return EXIT_USAGE
    env["DEVICE_ID"] = device_id or "dev-local"
    if args.interval is not None:
        env["DEVICE_SAMPLE_INTERVAL_S"] = str(args.interval)
    try:
        config = DeviceConfig.from_env(env)
    except ConfigError as exc:
        _error(str(exc))
        return EXIT_USAGE

    from board_runtime.main import run_loop

    sensors = None
    if config.sensors is SensorKind.FREEWILI:
        sensors = FreeWiliSensors(port=config.serial_port)
        try:
            sensors.connect()  # fail fast here instead of looping in "degraded"
        except FreeWiliNotInstalledError as exc:
            _error("the 'freewili' Python package is not installed", exc.hint)
            return EXIT_USAGE
        except BoardUnavailableError as exc:
            _error(str(exc), exc.hint)
            return EXIT_FAILED
        assert sensors.info is not None
        print(f"connected to {sensors.info.describe()}", file=sys.stderr)
    else:
        print("using simulated sensors (pass a port to use a real board)", file=sys.stderr)
    print(
        f"device id {config.device_id}; messages go to "
        f"{'AWS IoT' if config.transport is TransportKind.MQTT else 'stdout'}; Ctrl+C to stop",
        file=sys.stderr,
    )
    run_loop(config, samples=args.samples, sensors=sensors)
    return EXIT_OK


def cmd_sim(args: argparse.Namespace) -> int:
    from board_runtime.simulator import simulate

    env = dict(os.environ)
    env["BUILDERWARS_STATE_DIR"] = str(args.state_dir)
    env["DEVICE_ID"] = args.device_id
    csv_path = log_csv_path_from_env(env)  # None when BUILDERWARS_LOG_CSV=off
    simulate(
        device_id=args.device_id,
        count=args.count,
        seed=args.seed,
        csv_path=csv_path,
        write_csv=csv_path is not None,
    )
    if csv_path is not None:
        print(f"log messages also written to {csv_path}", file=sys.stderr)
    return EXIT_OK


# -- entry point ---------------------------------------------------------------------------
COMMANDS = ("test", "ports", "run", "sim", "show", "logs", "to-sql")
_GLOBAL_OPTIONS_WITH_VALUE = ("--state-dir",)


def _with_default_command(argv: list[str]) -> list[str]:
    """``builderwars /dev/ttyACM0 ...`` -> ``builderwars test /dev/ttyACM0 ...``."""
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            return argv
        if arg.startswith("-"):
            i += 2 if arg in _GLOBAL_OPTIONS_WITH_VALUE else 1
            continue
        if arg not in COMMANDS and _looks_like_port(arg):
            return [*argv[:i], "test", *argv[i:]]
        return argv
    return argv


def build_parser() -> argparse.ArgumentParser:
    prog = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "builderwars"
    if not prog.startswith("builderwars"):
        prog = "builderwars"
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Test a FREE-WILi board, run the host runtime, and manage local device logs.\n"
            "Quick start:  builderwars /dev/ttyACM0   (tests the board on that port)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=default_state_dir(),
        help="state dir holding the logs/ folder (default: ~/.builderwars)",
    )
    parser.add_argument("--debug", action="store_true", help="verbose logs and full tracebacks")
    # Accept the global options after the subcommand too (`builderwars run --debug`).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--state-dir", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument(
        "--debug", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p_test = sub.add_parser(
        "test",
        parents=[common],
        help="check a board step by step and read its GPIO/buttons (default for a port argument)",
        description="Check a FREE-WILi step by step; every failure says what to do about it.",
    )
    p_test.add_argument(
        "port", nargs="?", help="serial port, e.g. /dev/ttyACM0 or ttyACM0 (default: first board)"
    )
    p_test.add_argument("-n", "--samples", type=int, default=3, help="reads to take (default 3)")
    p_test.add_argument(
        "-i", "--interval", type=float, default=0.5, help="seconds between reads (default 0.5)"
    )
    p_test.add_argument(
        "-w", "--watch", action="store_true", help="keep reading; print only changes (Ctrl+C)"
    )
    p_test.add_argument(
        "--timeout", type=float, default=6.0, help="seconds to wait for the port to open"
    )
    p_test.set_defaults(func=cmd_test)

    p_ports = sub.add_parser(
        "ports", parents=[common], help="list FREE-WILi boards and serial ports"
    )
    p_ports.set_defaults(func=cmd_ports)

    p_run = sub.add_parser(
        "run",
        parents=[common],
        help="run the host runtime (sample, batch, publish) on a board or simulated sensors",
        description=(
            "Run the full host runtime. With a port it uses that FREE-WILi; without one it "
            "follows DEVICE_SENSORS / DEVICE_PORT (default: simulated). Other settings come "
            "from the DEVICE_* / IOT_* environment variables (see device/README.md)."
        ),
    )
    p_run.add_argument("port", nargs="?", help="FREE-WILi serial port, e.g. /dev/ttyACM0")
    p_run.add_argument("--device-id", help="device id (default: $DEVICE_ID or dev-local)")
    p_run.add_argument("-n", "--samples", type=int, default=None, help="stop after N samples")
    p_run.add_argument("-i", "--interval", type=float, default=None, help="seconds per sample")
    p_run.set_defaults(func=cmd_run)

    p_sim = sub.add_parser(
        "sim", parents=[common], help="emit messages from a simulated board as JSON lines"
    )
    p_sim.add_argument("--device-id", default="sim-001")
    p_sim.add_argument("--count", type=int, default=5, help="number of sensor samples")
    p_sim.add_argument("--seed", type=int, default=None)
    p_sim.set_defaults(func=cmd_sim)

    p_show = sub.add_parser(
        "show", aliases=["logs"], parents=[common], help="list stored log CSVs with row counts"
    )
    p_show.set_defaults(func=cmd_show)

    p_sql = sub.add_parser(
        "to-sql",
        parents=[common],
        help="convert one log CSV into a self-contained .sql dump (asks [Y/n])",
    )
    p_sql.add_argument("csv", help="CSV path, or a device id (looked up under <state-dir>/logs)")
    p_sql.add_argument("-o", "--output", help="output .sql path (default: <csv>.sql next to it)")
    p_sql.add_argument("--yes", action="store_true", help="skip the [Y/n] prompt")
    p_sql.set_defaults(func=cmd_to_sql)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    args: Any = parser.parse_args(_with_default_command(raw))
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    for name in ("samples", "count"):
        value = getattr(args, name, None)
        if value is not None and value < 1:
            parser.error(f"--{name} must be at least 1")
    if getattr(args, "interval", None) is not None and args.interval <= 0:
        parser.error("--interval must be greater than 0")
    func = getattr(args, "func", cmd_home)
    try:
        return func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
    except Exception as exc:
        if args.debug:
            traceback.print_exc()
        else:
            _error(
                f"unexpected {type(exc).__name__}: {exc}",
                "re-run with --debug for the full traceback",
            )
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
