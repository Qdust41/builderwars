"""``builderwars`` board commands against a fake FREE-WILi (no hardware needed).

/dev/null and /dev/zero stand in for the board's two ttys: they are real character devices
every user can read and write, so the port preflight checks run for real.
"""

from __future__ import annotations

import os
from enum import Enum
from types import SimpleNamespace

import pytest

import board_runtime.cli as cli
import board_runtime.hardware.freewili as fw
from board_runtime.config import ConfigError, DeviceConfig, SensorKind
from board_runtime.hardware.freewili import FreeWiliNotInstalledError
from board_runtime.hardware.ports import PortProblem, check_port, permission_hint

pytestmark = pytest.mark.skipif(os.name != "posix", reason="uses /dev/null as a fake tty")


class Proc(Enum):
    Main = 1
    Display = 2


class Button(Enum):
    Red = 1
    Green = 2


class Ok:
    def __init__(self, value=None):
        self.value = value

    def is_err(self):
        return False

    def unwrap(self):
        return self.value


class Err:
    def __init__(self, error):
        self.error = error

    def is_err(self):
        return True

    def unwrap_err(self):
        return self.error


class FakeBoard:
    def __init__(
        self,
        main: str | None = "/dev/null",
        display: str | None = "/dev/zero",
        *,
        open_error: str | None = None,
        read_error: str | None = None,
    ) -> None:
        self.device = SimpleNamespace(
            name="FreeWili", serial="FW-TEST", device_type=SimpleNamespace(name="FreeWili")
        )
        self.main = SimpleNamespace(port=main) if main else None
        self.display = SimpleNamespace(port=display) if display else None
        self.open_error = open_error
        self.read_error = read_error
        self.closed = False
        self.reads = 0

    def open(self, block, timeout_sec):
        assert isinstance(timeout_sec, float)
        return Err(self.open_error) if self.open_error else Ok()

    def close(self):
        self.closed = True

    def get_io(self, processor):
        assert processor is Proc.Main
        self.reads += 1
        if self.read_error:
            return Err(self.read_error)
        return Ok((0, 1, 0, self.reads % 2))

    def read_all_buttons(self, processor):
        assert processor is Proc.Display
        return Ok({Button.Red: self.reads > 1, Button.Green: False})


@pytest.fixture
def boards(monkeypatch: pytest.MonkeyPatch) -> list[FakeBoard]:
    found: list[FakeBoard] = []
    module = SimpleNamespace(FreeWili=SimpleNamespace(find_all=lambda: tuple(found)))
    monkeypatch.setattr(fw, "import_freewili", lambda: (module, Proc))
    monkeypatch.setattr(cli, "import_freewili", lambda: (module, Proc))
    return found


def test_bare_port_argument_runs_the_board_test(boards, capsys) -> None:
    board = FakeBoard()
    boards.append(board)
    assert cli.main(["/dev/null", "-n", "2", "-i", "0.01"]) == 0
    out = capsys.readouterr().out
    assert "Testing FREE-WILi on /dev/null" in out
    assert "found FreeWili (serial FW-TEST, main /dev/null, display /dev/zero)" in out
    assert "GPIO[0-3] 0101  buttons: none pressed" in out
    assert "buttons: red pressed  changed: io_3 1->0, button_red False->True" in out
    assert out.rstrip().endswith("PASS")
    assert board.closed


def test_display_port_selects_the_same_board(boards, capsys) -> None:
    boards.append(FakeBoard())
    assert cli.main(["test", "/dev/zero", "-n", "1"]) == 0
    assert "display CPU's port" in capsys.readouterr().out


def test_port_of_another_device_lists_the_real_boards(boards, capsys) -> None:
    boards.append(FakeBoard(main="/dev/null", display=None))
    assert cli.main(["/dev/zero"]) == 1
    out = capsys.readouterr().out
    assert "/dev/zero is not a FREE-WILi serial port" in out
    assert "FreeWili (serial FW-TEST, main /dev/null)" in out
    assert out.rstrip().endswith("FAIL")


def test_no_board_found(boards, capsys) -> None:
    assert cli.main(["test"]) == 1
    assert "no FREE-WILi board found on USB" in capsys.readouterr().out


def test_busy_port_explains_who_to_close(boards, capsys, monkeypatch) -> None:
    monkeypatch.setattr("board_runtime.hardware.ports.holders", lambda port: [])
    board = FakeBoard(open_error="[Errno 16] Device or resource busy")
    boards.append(board)
    assert cli.main(["/dev/null"]) == 1
    out = capsys.readouterr().out
    assert "could not open the board's serial ports" in out
    assert "another program has the port open" in out
    assert board.closed


def test_exclusive_lock_error_names_the_builderwars_holding_the_port(
    boards, capsys, monkeypatch
) -> None:
    seen: list[str] = []

    def holders(port: str) -> list[tuple[int, str]]:
        seen.append(port)
        return [(4242, "python -m board_runtime.cli run --cloud --device-id dev_1")]

    monkeypatch.setattr("board_runtime.hardware.ports.holders", holders)
    boards.append(
        FakeBoard(
            open_error="[Errno 11] Could not exclusively lock port /dev/ttyACM2: "
            "[Errno 11] Resource temporarily unavailable"
        )
    )
    assert cli.main(["/dev/null"]) == 1
    out = capsys.readouterr().out
    assert seen == ["/dev/ttyACM2"]  # the display port named in the error, not the main one
    assert "pid 4242" in out
    assert "another builderwars on this laptop" in out
    assert "kill 4242" in out


def test_read_error_fails_with_the_board_message(boards, capsys) -> None:
    boards.append(FakeBoard(read_error="timeout waiting for response"))
    assert cli.main(["/dev/null"]) == 1
    out = capsys.readouterr().out
    assert "read #1 failed: reading GPIO from the main CPU failed: timeout" in out


def test_missing_freewili_package(monkeypatch, capsys) -> None:
    def missing():
        raise FreeWiliNotInstalledError()

    monkeypatch.setattr(cli, "import_freewili", missing)
    assert cli.main(["/dev/null"]) == 1
    assert "uv sync" in capsys.readouterr().out


def test_missing_port_names_the_problem(capsys, tmp_path) -> None:
    assert cli.main([str(tmp_path / "ttyACM9")]) == 1
    assert "does not exist" in capsys.readouterr().out


def test_no_arguments_shows_boards_and_next_steps(boards, capsys) -> None:
    boards.append(FakeBoard())
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "FREE-WILi boards:" in out
    assert "builderwars /dev/null" in out


def test_run_fails_fast_when_the_board_is_missing(boards, capsys, tmp_path) -> None:
    assert cli.main(["run", "/dev/null", "--state-dir", str(tmp_path)]) == 1
    assert "no FREE-WILi board was found on USB" in capsys.readouterr().err


def test_default_command_insertion() -> None:
    assert cli._with_default_command(["/dev/ttyACM0", "-w"]) == ["test", "/dev/ttyACM0", "-w"]
    assert cli._with_default_command(["--state-dir", "x", "ttyACM0"]) == [
        "--state-dir",
        "x",
        "test",
        "ttyACM0",
    ]
    assert cli._with_default_command(["COM3"]) == ["test", "COM3"]
    assert cli._with_default_command(["show"]) == ["show"]
    assert cli._with_default_command(["tset"]) == ["tset"]  # typo -> argparse error, not a port


def test_bare_tty_name_is_normalised() -> None:
    assert cli.normalize_port("ttyACM0") == "/dev/ttyACM0"
    assert cli.normalize_port("/dev/ttyACM0") == "/dev/ttyACM0"
    assert cli.normalize_port(None) is None


def test_check_port_rejects_non_devices(tmp_path) -> None:
    with pytest.raises(PortProblem, match="directory, not a serial device"):
        check_port(str(tmp_path))
    regular = tmp_path / "file"
    regular.write_text("x")
    with pytest.raises(PortProblem, match="regular file"):
        check_port(str(regular))
    check_port("/dev/null")  # a readable/writable character device passes


def test_permission_hint_names_group_and_command(tmp_path) -> None:
    hint = permission_hint(str(tmp_path))
    assert "fix:" in hint or "log out" in hint
    assert "chmod a+rw" in hint


def test_device_port_env_implies_freewili_and_bad_values_are_explained() -> None:
    cfg = DeviceConfig.from_env({"DEVICE_ID": "d", "DEVICE_PORT": "/dev/ttyACM0"})
    assert cfg.sensors is SensorKind.FREEWILI
    assert cfg.serial_port == "/dev/ttyACM0"
    with pytest.raises(ConfigError, match="DEVICE_SENSORS='usb' is not valid; use one of"):
        DeviceConfig.from_env({"DEVICE_ID": "d", "DEVICE_SENSORS": "usb"})
    with pytest.raises(ConfigError, match="DEVICE_SAMPLE_INTERVAL_S='fast' is not a number"):
        DeviceConfig.from_env({"DEVICE_ID": "d", "DEVICE_SAMPLE_INTERVAL_S": "fast"})


# -- a busy port: retried, and a held board is refused before the port is touched ------------
class BusyThenFree(FakeBoard):
    """Busy (another process has it) for the first ``busy`` opens, then opens fine."""

    def __init__(self, busy: int) -> None:
        super().__init__()
        self.busy = busy
        self.opens = 0

    def open(self, block, timeout_sec):
        self.opens += 1
        if self.opens <= self.busy:
            print("[Errno 11] Could not exclusively lock port /dev/zero: [Errno 11] Resource ...")
            return Err("Failed to open in 6.0 seconds: ")
        return Ok()


def test_a_busy_port_is_retried_until_it_frees(boards, monkeypatch, capsys) -> None:
    monkeypatch.setattr(fw.time, "sleep", lambda s: None)
    board = BusyThenFree(busy=2)
    boards.append(board)
    sensors = fw.FreeWiliSensors(port=None, busy_wait_s=30)
    assert sensors.connect() is board
    assert board.opens == 3
    assert "Errno 11" not in capsys.readouterr().out  # the library's print is captured


def test_a_port_that_stays_busy_says_who_has_it(boards, monkeypatch) -> None:
    monkeypatch.setattr(fw.time, "sleep", lambda s: None)
    monkeypatch.setattr("board_runtime.hardware.ports.holders", lambda port: [(7, "minicom")])
    boards.append(BusyThenFree(busy=99))
    with pytest.raises(fw.BoardUnavailableError) as raised:
        fw.FreeWiliSensors(port=None, busy_wait_s=0).connect()
    assert "Could not exclusively lock port /dev/zero" in str(raised.value)
    assert "pid 7: minicom" in (raised.value.hint or "")


def test_run_refuses_a_held_board_before_opening_the_freewili(
    boards, monkeypatch, tmp_path, capsys
) -> None:
    from board_runtime.cloud import ApiError, SensorList

    board = BusyThenFree(busy=99)
    boards.append(board)

    class HeldElsewhere:
        account = SimpleNamespace(email="me@example.com")

        def request(self, method, path, body=None):
            if method == "PUT":
                raise ApiError(
                    409,
                    "this board is in use by bob@example.com's run on lab-pc (started 10:00 UTC)",
                    code="board_in_use",
                )
            return {"display_name": "Bench"}

    monkeypatch.setattr(cli, "_session", lambda state_dir: HeldElsewhere())
    monkeypatch.setattr("board_runtime.cloud.fetch_sensors", lambda s, d: SensorList())
    code = cli.main(["run", "--cloud", "--device-id", "dev_1", "--state-dir", str(tmp_path)])
    assert code == 1
    assert "bob@example.com's run on lab-pc" in capsys.readouterr().err
    assert board.opens == 0  # the port the other run holds was never touched


# -- the bench case: a time-out must not leave the display port open --------------------------
class _Serial:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.closed_with: dict | None = None

    def close(self, restore_menu=True, block=True, timeout_sec=6.0):
        self.closed_with = {"restore_menu": restore_menu, "timeout_sec": timeout_sec}
        if self.fail:
            raise TimeoutError("Failed to close serial port in 6.0 seconds.")


def test_closing_closes_the_display_port_even_when_the_main_port_hangs() -> None:
    board = SimpleNamespace(_main_serial=_Serial(fail=True), _display_serial=_Serial())
    fw.close_quietly(board)
    assert board._display_serial.closed_with == {"restore_menu": False, "timeout_sec": 3.0}
    assert board._main_serial.closed_with is not None


def test_a_slow_answer_keeps_the_ports_open_and_retries(boards) -> None:
    board = FakeBoard(read_error="Failed to read response frame in 6.0 seconds: ")
    boards.append(board)
    reader = fw.FreeWiliSensors(port=None)
    reader._injected = False  # a real (discovered) board, as in `builderwars run`
    for _ in range(fw.REOPEN_AFTER_FAILURES - 1):
        with pytest.raises(fw.BoardUnavailableError):
            reader.read()
    assert not board.closed  # still open: the next read asks again
    board.read_error = None
    assert "io_0" in reader.read()
    board.read_error = "Failed to read response frame in 6.0 seconds: "
    for _ in range(fw.REOPEN_AFTER_FAILURES):
        with pytest.raises(fw.BoardUnavailableError) as raised:
            reader.read()
    assert "re-opening the FREE-WILi" in str(raised.value)
    assert board.closed
