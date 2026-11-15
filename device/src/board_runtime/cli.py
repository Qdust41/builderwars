"""``builderwars`` — test a FREE-WILi board, run the host runtime, and manage local logs.

    builderwars                         # list FREE-WILi boards / serial ports, show next steps
    builderwars /dev/ttyACM0            # test that board (same as: builderwars test /dev/ttyACM0)
    builderwars test --watch            # first board found; print GPIO/button changes live
    builderwars ports                   # list boards and serial ports with permission status
    builderwars run /dev/ttyACM0        # full host runtime on that board, messages to stdout
    builderwars sim --count 40          # simulated board, messages to stdout
    builderwars show                    # list the log CSVs stored on this computer
    builderwars to-sql sim-001          # asks [Y/n], writes sim-001.sql next to the CSV
    builderwars login                   # sign in to your Builderwars account
    builderwars devices                 # your registered devices and their ids
    builderwars run --cloud --device-id dev_...   # read the device's sensors, stream live
    builderwars run --cloud --simulate --device-id dev_...   # same, made-up values, no board
    builderwars sensors dev_... --read  # list a device's sensors and read each once
    builderwars upload run.jsonl --device-id dev_...  # upload saved telemetry/logs
    builderwars logs dev_...            # download a device's cloud logs to dev_...-logs.csv

The device runtime and simulator append every log message they send to the cloud to a local
CSV under ``~/.builderwars/logs/<device-id>.csv`` (override with ``BUILDERWARS_LOG_CSV``);
``to-sql`` turns one into a self-contained ``.sql`` dump for PostgreSQL or SQLite.
``logs`` downloads what the cloud stored for a device (as the signed-in user) into a CSV.

Exit codes: 0 ok, 1 board test failed, 2 usage/setup error, 130 interrupted.
``builderwars-logs`` is the same program (kept for compatibility).
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import dataclasses
import logging
import os
import shlex
import signal
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
from board_runtime.hardware.configured import (
    ConfiguredSensors,
    SensorReadError,
    SimulatedConfiguredSensors,
    SimulatedFaults,
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
from board_runtime.hardware.sensors import BoardUnavailableError, SimulatedSensors
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


def _cli_version() -> str:
    try:
        from importlib.metadata import version

        return version("bw-board-runtime")
    except Exception:
        return "dev"


def cmd_run(args: argparse.Namespace) -> int:
    port = normalize_port(args.port)
    simulate = bool(getattr(args, "simulate", False))
    if simulate and port:
        _error("--simulate and a port don't go together", "drop one of them")
        return EXIT_USAGE
    env = dict(os.environ)
    env.setdefault("BUILDERWARS_STATE_DIR", str(args.state_dir))
    if port:
        env["DEVICE_PORT"] = port
    device_id = args.device_id or env.get("DEVICE_ID")
    if getattr(args, "cloud", False):
        env["DEVICE_TRANSPORT"] = TransportKind.CLOUD.value
    cloud = (env.get("DEVICE_TRANSPORT") or "").strip().lower() == TransportKind.CLOUD
    if simulate:
        env["DEVICE_SENSORS"] = SensorKind.SIMULATED.value
        env.pop("DEVICE_PORT", None)
    elif cloud and not env.get("DEVICE_SENSORS"):
        # Streaming to the dashboard reads the real FREE-WILi; simulation must be asked for.
        env["DEVICE_SENSORS"] = SensorKind.FREEWILI.value
    if not device_id and cloud:
        _error(
            "--cloud needs the registered device id",
            "pass --device-id dev_... (`builderwars devices` lists yours)",
        )
        return EXIT_USAGE
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

    destination = {
        TransportKind.MQTT: "AWS IoT",
        TransportKind.LOCAL_API: config.local_api_url,
        TransportKind.STDOUT: "stdout",
    }.get(config.transport, "")
    session: Any = None
    sensor_list: Any = None
    if config.transport is TransportKind.CLOUD:
        from urllib.parse import quote

        from board_runtime.cloud import AccountError, fetch_sensors

        try:  # fail now, not after the board is connected, if the id or sign-in is wrong
            session = _session(config.state_dir or args.state_dir)
            device = session.request("GET", f"/devices/{quote(config.device_id, safe='')}")
            sensor_list = fetch_sensors(session, config.device_id)
        except AccountError as exc:
            return _account_error(exc)
        destination = (
            f"Builderwars ({device['display_name']}, as {session.account.email}); "
            "the web dashboard shows them live"
        )
        for key, why in sensor_list.skipped:
            print(f"skipping sensor {key}: {why} (update the CLI?)", file=sys.stderr)

    specs = [s for s in (sensor_list.sensors if sensor_list else []) if s.enabled]
    refresh: Any = None
    if session is not None:
        from board_runtime.cloud import fetch_sensors

        # Sensors and boards added on the device page while this runs are picked up (30 s).
        def refresh() -> list[Any]:
            return fetch_sensors(session, config.device_id).sensors

    sensors: Any = None
    board_info: BoardInfo | None = None
    if config.sensors is SensorKind.FREEWILI:
        board = FreeWiliSensors(port=config.serial_port)
        try:
            board.connect()  # fail fast here instead of looping in "degraded"
        except FreeWiliNotInstalledError as exc:
            _error("the 'freewili' Python package is not installed", exc.hint)
            return EXIT_USAGE
        except BoardUnavailableError as exc:
            hint = exc.hint or ""
            if cloud:
                hint += "\nno board at hand? `--simulate` sends made-up values instead"
            _error(str(exc), hint.strip() or None)
            return EXIT_FAILED
        board_info = board.info
        assert board_info is not None
        print(f"connected to {board_info.describe()}", file=sys.stderr)
        source = "freewili" if specs else "freewili-gpio"
        if specs or refresh is not None:
            # Without sensors yet, send the FREE-WILi's own pins until some are defined.
            sensors = ConfiguredSensors(specs, board, refresh=refresh, fallback=board)
        else:
            sensors = board
        if not specs and cloud:
            print(
                "no sensors are defined for this device yet: sending the FREE-WILi's own "
                "pin levels.\nAdd target boards and sensors on the device page; they are "
                "picked up within 30 s.",
                file=sys.stderr,
            )
    else:
        source = "simulated"
        error_rate = float(getattr(args, "sim_errors", 0.0) or 0.0)
        faults = SimulatedFaults(error_rate) if error_rate > 0 else None
        sensors = SimulatedConfiguredSensors(
            specs, refresh=refresh, fallback=SimulatedSensors(), faults=faults
        )
        if specs:
            print("SIMULATED values for this device's sensors (no board is read)", file=sys.stderr)
        else:
            hint = "" if simulate else " (pass a port to use a real board)"
            print(f"using simulated sensors{hint}", file=sys.stderr)
        if faults is not None:
            print(
                f"with made-up faults about {error_rate:.0%} of the time "
                "(--sim-errors 0 turns them off)",
                file=sys.stderr,
            )

    if specs:
        width = max(len(s.key) for s in specs) + 2
        print(f"reading {len(specs)} sensor(s):", file=sys.stderr)
        for spec in specs:
            board_name = sensor_list.boards.get(spec.key, "") if sensor_list else ""
            where = f"  [{board_name}]" if board_name else ""
            every = f"every {spec.poll_interval_s:g} s"
            print(f"  {spec.key:<{width}}{describe_bus(spec)}, {every}{where}", file=sys.stderr)
        for warning in i2c_address_clashes(specs, sensor_list.boards if sensor_list else {}):
            print(f"warning: {warning}", file=sys.stderr)
        fastest = min(s.poll_interval_s for s in specs)
        if args.interval is None and fastest < config.sample_interval_s:
            config = dataclasses.replace(config, sample_interval_s=fastest)

    run_id: str | None = None
    if session is not None:
        from board_runtime.cloud import (
            BoardInUseError,
            bridge_report,
            host_report,
            new_run_id,
            report_connection,
        )

        run_id = new_run_id()
        try:  # lock the board for this run: one `builderwars run` at a time per device
            report_connection(
                session,
                config.device_id,
                host_report(cli_version=_cli_version(), sensor_source=source),
                bridge_report(board_info, library_version=_freewili_version()),
                run_id=run_id,
                take_over=bool(getattr(args, "take_over", False)),
            )
        except BoardInUseError as exc:
            _close_quietly(sensors)
            _error(str(exc), exc.hint)
            return EXIT_FAILED
        config = dataclasses.replace(config, run_id=run_id)
        print(
            "this run has locked the board; other runs are refused until it stops", file=sys.stderr
        )
    print(
        f"device id {config.device_id}; messages go to {destination}; Ctrl+C to stop",
        file=sys.stderr,
    )
    _stop_on_signals()  # closing the terminal or `kill` also releases the board
    try:
        stop_reason = run_loop(config, samples=args.samples, sensors=sensors)
    finally:
        if session is not None and run_id is not None:
            from board_runtime.cloud import release_run

            release_run(session, config.device_id, run_id)
        _close_quietly(sensors)
    if stop_reason:
        _error(stop_reason, "someone ran `builderwars run --take-over` for this device")
        return EXIT_FAILED
    return EXIT_OK


def i2c_address_clashes(specs: list[Any], boards: dict[str, str]) -> list[str]:
    """The FREE-WILi has one I2C bus for all target boards, so the same address on two boards
    can't be told apart (one chip answers, or both garble the reply)."""
    from device_protocol.sensors import I2CBus

    seen: dict[int, set[str]] = {}
    for spec in specs:
        if isinstance(spec.bus, I2CBus):
            seen.setdefault(spec.bus.address, set()).add(boards.get(spec.key, ""))
    return [
        f"I2C address 0x{address:02X} is used on {len(names)} boards ({', '.join(sorted(names))}); "
        "the FREE-WILi shares one I2C bus, so only one chip there can answer"
        for address, names in sorted(seen.items())
        if len(names - {""}) > 1
    ]


def _stop_on_signals() -> None:
    """SIGTERM/SIGHUP stop the run like Ctrl+C, so it says goodbye and frees the board."""

    def stop(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is not None:
            with contextlib.suppress(ValueError, OSError):  # not the main thread / platform
                signal.signal(sig, stop)


def _rate(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not 0.0 <= value <= 1.0:
        raise argparse.ArgumentTypeError("use a rate between 0 and 1, e.g. 0.05")
    return value


def _close_quietly(sensors: Any) -> None:
    close = getattr(sensors, "close", None)
    if callable(close):
        with contextlib.suppress(Exception):  # best effort on the way out
            close()


def describe_bus(spec: Any) -> str:
    """One line saying where a sensor is read, e.g. ``I2C 0x48 reg 0x00 (2 bytes)``."""
    bus = spec.bus
    if bus.protocol == "i2c":
        setup = f", {len(bus.setup_writes)} setup write(s)" if bus.setup_writes else ""
        return f"I2C 0x{bus.address:02X} reg 0x{bus.reg:02X} ({bus.length} bytes{setup})"
    if bus.protocol == "spi":
        sent = " ".join(f"{b:02X}" for b in bus.write)
        return (
            f"SPI send [{sent}], keep bytes {bus.read_offset}..{bus.read_offset + bus.length - 1}"
        )
    if bus.protocol == "uart":
        return f"UART {bus.command!r}" if bus.command else "UART (listen)"
    return f"GPIO{bus.pin}"


def cmd_sensors(args: argparse.Namespace) -> int:
    """List a device's sensors; with --read, read each once through the FREE-WILi."""
    from board_runtime.cloud import AccountError, fetch_sensors

    try:
        session = _session(args.state_dir)
        device_id, name = _resolve_device(session, args.device)
        listed = fetch_sensors(session, device_id)
    except AccountError as exc:
        return _account_error(exc)
    for key, why in listed.skipped:
        print(f"skipping sensor {key}: {why} (update the CLI?)", file=sys.stderr)
    if not listed.sensors:
        print(f"{name} has no sensors yet. Add target boards and sensors on its device page.")
        return EXIT_OK
    width = max(len(s.key) for s in listed.sensors) + 2
    if not args.read:
        print(f"Sensors of {name} ({device_id}):")
        for spec in listed.sensors:
            state = "" if spec.enabled else "  (disabled)"
            unit = f" [{spec.unit}]" if spec.unit else ""
            board_name = listed.boards.get(spec.key)
            where = f"  on {board_name}" if board_name else ""
            print(f"  {spec.key:<{width}}{describe_bus(spec)}{unit}{where}{state}")
        print(f"Read them once on the board: builderwars sensors {shlex.quote(args.device)} --read")
        return EXIT_OK

    board = FreeWiliSensors(port=normalize_port(args.port))
    try:
        device = board.connect()
    except FreeWiliNotInstalledError as exc:
        _error("the 'freewili' Python package is not installed", exc.hint)
        return EXIT_USAGE
    except BoardUnavailableError as exc:
        _error(str(exc), exc.hint)
        return EXIT_FAILED
    assert board.info is not None
    print(f"reading through {board.info.describe()}")
    reader = ConfiguredSensors(listed.sensors, board)
    failed = 0
    try:
        for spec in listed.sensors:
            try:
                value = reader.read_one(device, spec)
            except (SensorReadError, ValueError) as exc:
                failed += 1
                print(f"  {spec.key:<{width}}FAILED: {exc}")
                continue
            print(f"  {spec.key:<{width}}{value}{' ' + spec.unit if spec.unit else ''}")
    finally:
        board.close()
    return EXIT_FAILED if failed else EXIT_OK


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


# -- account and cloud upload ----------------------------------------------------------------
def _account_error(exc: Exception) -> int:
    _error(str(exc), getattr(exc, "hint", None))
    return EXIT_FAILED


def cmd_login(args: argparse.Namespace) -> int:
    import getpass

    from board_runtime.cloud import AccountError, login

    api_url = args.api or os.environ.get("BUILDERWARS_API_URL") or _saved_api_url(args.state_dir)
    email = args.email or input("Email: ").strip()
    if not email:
        _error("an email is required")
        return EXIT_USAGE

    def new_password() -> str:
        print("This account has a temporary password; choose a new one.", file=sys.stderr)
        first = getpass.getpass("New password: ")
        if first != getpass.getpass("New password again: "):
            raise AccountError("the new passwords do not match")
        return first

    try:
        account = login(
            api_url=api_url,
            email=email,
            password=lambda: getpass.getpass("Password: "),
            new_password=new_password,
            state_dir=args.state_dir,
        )
    except AccountError as exc:
        return _account_error(exc)
    mode = " (local dev API)" if account.auth_mode == "dev-header" else ""
    print(f"Signed in as {account.email} to {account.api_url}{mode}.")
    print("Next: `builderwars devices` to find your device id, then")
    print("      `builderwars run --cloud --device-id dev_...` to stream a board live.")
    return EXIT_OK


def _saved_api_url(state_dir: Path) -> str:
    from board_runtime.cloud import DEFAULT_API_URL, Account, AccountError

    try:
        return Account.load(state_dir).api_url
    except AccountError:
        return DEFAULT_API_URL


def cmd_logout(args: argparse.Namespace) -> int:
    from board_runtime.cloud import Account

    if Account.forget(args.state_dir):
        print("Signed out; the saved sign-in was deleted.")
    else:
        print("Not signed in.")
    return EXIT_OK


def _session(state_dir: Path) -> Any:
    from board_runtime.cloud import CloudSession

    return CloudSession.load(state_dir)


def cmd_whoami(args: argparse.Namespace) -> int:
    from board_runtime.cloud import AccountError

    try:
        session = _session(args.state_dir)
        projects = session.request("GET", "/projects") or []
    except AccountError as exc:
        return _account_error(exc)
    account = session.account
    print(f"{account.email} on {account.api_url} ({len(projects)} project(s))")
    return EXIT_OK


def cmd_devices(args: argparse.Namespace) -> int:
    from urllib.parse import quote

    from board_runtime.cloud import AccountError

    try:
        session = _session(args.state_dir)
        projects = session.request("GET", "/projects") or []
        rows = []
        for project in projects:
            path = f"/projects/{quote(project['id'], safe='')}/devices"
            for device in session.request("GET", path) or []:
                rows.append((device["id"], device["display_name"], project["name"]))
    except AccountError as exc:
        return _account_error(exc)
    if not rows:
        print("No devices yet. Register one in the web app (a project's Devices list).")
        return EXIT_OK
    width = max(len(r[0]) for r in rows) + 2
    name_width = max(len(r[1]) for r in rows) + 2
    print(f"{'DEVICE ID':<{width}}{'NAME':<{name_width}}PROJECT")
    for device_id, name, project in rows:
        print(f"{device_id:<{width}}{name:<{name_width}}{project}")
    return EXIT_OK


UPLOAD_CHUNK = 200  # the API's per-request limit


def cmd_upload(args: argparse.Namespace) -> int:
    from board_runtime.cloud import AccountError, CloudApiTransport, read_messages

    path = Path(args.file).expanduser()
    if not path.is_file():
        candidate = _logs_dir(args.state_dir) / f"{path.name}.csv"
        if not candidate.is_file():
            _error(f"file not found: {args.file}", "pass a .jsonl from `run`/`sim` or a log CSV")
            return EXIT_USAGE
        path = candidate
    try:
        read = read_messages(path, args.device_id)
    except (OSError, ValueError) as exc:
        _error(str(exc))
        return EXIT_USAGE
    for reason in read.skipped[:10]:
        print(f"skipped {reason}", file=sys.stderr)
    if len(read.skipped) > 10:
        print(f"... and {len(read.skipped) - 10} more skipped", file=sys.stderr)
    if not read.messages:
        print(f"Nothing to upload from {path}.")
        return EXIT_FAILED if read.skipped else EXIT_OK

    totals = {"processed": 0, "duplicate": 0, "rejected": 0}
    rejected: list[str] = []
    try:
        transport = CloudApiTransport(_session(args.state_dir), args.device_id)
        for start in range(0, len(read.messages), UPLOAD_CHUNK):
            result = transport.upload(read.messages[start : start + UPLOAD_CHUNK])
            for key in totals:
                totals[key] += int(result.get(key, 0))
            rejected += [
                str(item.get("detail") or item.get("reason"))
                for item in result.get("results", [])
                if item.get("outcome") == "rejected"
            ]
            print(
                f"\ruploaded {min(start + UPLOAD_CHUNK, len(read.messages))}/{len(read.messages)}",
                end="",
                file=sys.stderr,
            )
        print(file=sys.stderr)
    except AccountError as exc:
        print(file=sys.stderr)
        return _account_error(exc)
    print(
        f"{path.name} -> {args.device_id}: {totals['processed']} new, "
        f"{totals['duplicate']} already uploaded, {totals['rejected']} rejected"
    )
    for detail in rejected[:5]:
        print(f"  rejected: {detail}", file=sys.stderr)
    return EXIT_FAILED if totals["rejected"] or read.skipped else EXIT_OK


def _parse_when(value: str) -> datetime:
    """ISO date or date-time; ``Z`` suffix allowed; no timezone means local time."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a date/time; use e.g. 2026-11-14 or 2026-11-14T09:30"
        ) from None
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


def _resolve_device(session: Any, wanted: str) -> tuple[str, str]:
    """Accept a device id or a device name; return ``(id, name)``."""
    from urllib.parse import quote

    from board_runtime.cloud import AccountError, ApiError

    if wanted.startswith("dev_"):
        try:
            device = session.request("GET", f"/devices/{quote(wanted, safe='')}")
            return device["id"], device.get("display_name") or wanted
        except ApiError as exc:
            if exc.status != 404:
                raise
    matches: list[tuple[str, str, str]] = []
    for project in session.request("GET", "/projects") or []:
        path = f"/projects/{quote(project['id'], safe='')}/devices"
        for device in session.request("GET", path) or []:
            if wanted in (device["id"], device["display_name"]) or (
                device["display_name"].casefold() == wanted.casefold()
            ):
                matches.append((device["id"], device["display_name"], project["name"]))
    if not matches:
        raise AccountError(
            f"no device {wanted!r} in your projects", "`builderwars devices` lists the ones you see"
        )
    if len(matches) > 1:
        listed = ", ".join(f"{d} ({n}, {p})" for d, n, p in matches)
        raise AccountError(
            f"{len(matches)} devices are named {wanted!r}: {listed}", "pass the device id instead"
        )
    return matches[0][0], matches[0][1]


def cmd_logs(args: argparse.Namespace) -> int:
    if not args.device:
        print("Logs stored on this computer (pass a device to download its cloud logs):")
        return cmd_show(args)

    from board_runtime.cloud import AccountError, export_logs_csv, iter_log_history, write_log_csv

    if args.since and args.until and args.since >= args.until:
        _error("--since must be before --until")
        return EXIT_USAGE
    try:
        session = _session(args.state_dir)
        device_id, name = _resolve_device(session, args.device)
        if args.output == "-":
            count = write_log_csv(
                sys.stdout,
                device_id,
                iter_log_history(session, device_id, since=args.since, until=args.until),
            )
            print(f"{count} entries from {name} ({device_id})", file=sys.stderr)
            return EXIT_OK
        output = Path(args.output) if args.output else Path(f"{device_id}-logs.csv")
        if output.exists() and not args.force:
            _error(f"{output} already exists", "pass --force to overwrite it, or -o another path")
            return EXIT_USAGE

        def progress(total: int) -> None:
            print(f"\rdownloaded {total} entries", end="", file=sys.stderr, flush=True)

        try:
            count = export_logs_csv(
                session, device_id, output, since=args.since, until=args.until, on_page=progress
            )
        finally:
            print(file=sys.stderr)
    except AccountError as exc:
        return _account_error(exc)
    except OSError as exc:
        _error(f"cannot write the CSV: {exc}")
        return EXIT_USAGE
    noun = "entry" if count == 1 else "entries"
    print(f"Wrote {output} ({count} {noun} from {name}, {device_id}).")
    if count == 0:
        print("The cloud has no logs for this device yet (in that time range).")
    return EXIT_OK


# -- entry point ---------------------------------------------------------------------------
COMMANDS = (
    "test",
    "ports",
    "run",
    "sim",
    "show",
    "logs",
    "to-sql",
    "login",
    "logout",
    "whoami",
    "devices",
    "upload",
)
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
            "Run the full host runtime. With --cloud it downloads the sensors defined on the "
            "device page and reads them through the FREE-WILi (the given port, or the first "
            "one found); --simulate sends made-up values instead. Without --cloud, a port "
            "means that FREE-WILi's own pins and no port means simulated values. Other "
            "settings come from the DEVICE_* / IOT_* environment variables (device/README.md)."
        ),
    )
    p_run.add_argument("port", nargs="?", help="FREE-WILi serial port, e.g. /dev/ttyACM0")
    p_run.add_argument("--device-id", help="device id (default: $DEVICE_ID or dev-local)")
    p_run.add_argument("-n", "--samples", type=int, default=None, help="stop after N samples")
    p_run.add_argument("-i", "--interval", type=float, default=None, help="seconds per sample")
    p_run.add_argument(
        "--cloud",
        action="store_true",
        help="send to Builderwars as the signed-in user (`builderwars login`); live dashboard. "
        "Reads the sensors defined on the device page through the FREE-WILi",
    )
    p_run.add_argument(
        "--simulate",
        action="store_true",
        help="no hardware: send made-up values (for the device's defined sensors, if any)",
    )
    p_run.add_argument(
        "--sim-errors",
        type=_rate,
        default=0.05,
        metavar="RATE",
        help="with --simulate: how often to make up faults (sensor read errors, USB drop-outs, "
        "board error logs), 0..1 (default 0.05; 0 turns them off)",
    )
    p_run.add_argument(
        "--take-over",
        action="store_true",
        help="--cloud: take the board from another run that holds it (that run stops)",
    )
    p_run.set_defaults(func=cmd_run)

    p_sim = sub.add_parser(
        "sim", parents=[common], help="emit messages from a simulated board as JSON lines"
    )
    p_sim.add_argument("--device-id", default="sim-001")
    p_sim.add_argument("--count", type=int, default=5, help="number of sensor samples")
    p_sim.add_argument("--seed", type=int, default=None)
    p_sim.set_defaults(func=cmd_sim)

    p_show = sub.add_parser(
        "show", parents=[common], help="list the log CSVs stored on this computer"
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

    p_login = sub.add_parser(
        "login",
        parents=[common],
        help="sign in to your Builderwars account (same email + password as the web app)",
        description=(
            "Sign in so the CLI can upload your board's telemetry and logs. The password goes "
            "to the sign-in service only and is never saved; <state-dir>/account.json keeps a "
            "refresh token (30 days) until `builderwars logout`."
        ),
    )
    p_login.add_argument(
        "--api",
        help="API address (default: $BUILDERWARS_API_URL, the last one used, or "
        "https://builderwars.jimweaver.com/api; http://localhost:8000 for a local API)",
    )
    p_login.add_argument("--email", help="account email (asked for when omitted)")
    p_login.set_defaults(func=cmd_login)

    p_logout = sub.add_parser("logout", parents=[common], help="forget the saved sign-in")
    p_logout.set_defaults(func=cmd_logout)

    p_whoami = sub.add_parser("whoami", parents=[common], help="show who you are signed in as")
    p_whoami.set_defaults(func=cmd_whoami)

    p_devices = sub.add_parser(
        "devices", parents=[common], help="list the devices in your projects, with their ids"
    )
    p_devices.set_defaults(func=cmd_devices)

    p_sensors = sub.add_parser(
        "sensors",
        parents=[common],
        help="list a device's sensors (defined on the device page); --read reads each once",
    )
    p_sensors.add_argument("device", help="device id or name (`builderwars devices`)")
    p_sensors.add_argument(
        "--read", action="store_true", help="read every sensor once through the FREE-WILi"
    )
    p_sensors.add_argument("--port", help="FREE-WILi serial port (default: first board found)")
    p_sensors.set_defaults(func=cmd_sensors)

    p_upload = sub.add_parser(
        "upload",
        parents=[common],
        help="upload saved telemetry/logs (.jsonl from run/sim, or a log CSV) to a device",
        description=(
            "Upload a file of board messages to a registered device: JSON lines from "
            "`builderwars run`/`sim`, or a log CSV from <state-dir>/logs. Re-uploading is "
            "harmless (messages already stored are counted, not duplicated)."
        ),
    )
    p_upload.add_argument("file", help="file path, or a device id whose log CSV to upload")
    p_upload.add_argument(
        "--device-id", required=True, help="registered device id, e.g. dev_... (see `devices`)"
    )
    p_upload.set_defaults(func=cmd_upload)

    p_logs = sub.add_parser(
        "logs",
        parents=[common],
        help="download a device's logs from the cloud into a CSV (`login` first)",
        description=(
            "Download every log line and device event the cloud stored for a device, oldest "
            "first, as the signed-in user, and write them to a CSV with the columns "
            "timestamp, device_id, kind, level, message, message_id. Without a device it "
            "lists the log CSVs stored on this computer (like `show`)."
        ),
    )
    p_logs.add_argument(
        "device", nargs="?", help="device id (dev_...) or device name; see `builderwars devices`"
    )
    p_logs.add_argument(
        "-o", "--output", help="CSV path (default: ./<device-id>-logs.csv; - for stdout)"
    )
    p_logs.add_argument(
        "--since", type=_parse_when, help="only entries at or after this (e.g. 2026-11-14)"
    )
    p_logs.add_argument(
        "--until", type=_parse_when, help="only entries before this (e.g. 2026-11-15T12:00)"
    )
    p_logs.add_argument("--force", action="store_true", help="overwrite an existing CSV")
    p_logs.set_defaults(func=cmd_logs)
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
