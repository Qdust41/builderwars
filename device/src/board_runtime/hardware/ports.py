"""Serial-port preflight checks that turn "it doesn't work" into a specific cause + fix.

Pure stdlib, no ``freewili`` import, so it works (and is testable) without the vendor package.
Checks only run for POSIX device paths (``/dev/...``); Windows ``COMx`` names are passed through.
"""

from __future__ import annotations

import glob
import os
import re
import stat
import sys
from dataclasses import dataclass


class PortProblem(Exception):
    """A serial port can't be used. ``hint`` says how to fix it (may be multi-line)."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass(frozen=True)
class PortStatus:
    path: str
    accessible: bool
    alias: str | None = None  # stable /dev/serial/by-id name, when there is one


def _is_posix_device_path(port: str) -> bool:
    return os.name == "posix" and port.startswith("/")


def candidate_ports() -> list[str]:
    """USB serial ports present right now (best effort, platform specific)."""
    if sys.platform.startswith("linux"):
        patterns = ["/dev/ttyACM*", "/dev/ttyUSB*"]
    elif sys.platform == "darwin":
        patterns = ["/dev/cu.usbmodem*", "/dev/cu.usbserial*"]
    else:
        return []
    return sorted({path for pattern in patterns for path in glob.glob(pattern)})


def by_id_aliases() -> dict[str, str]:
    """Map real tty path -> stable ``/dev/serial/by-id/...`` name (Linux only)."""
    aliases: dict[str, str] = {}
    for link in glob.glob("/dev/serial/by-id/*"):
        aliases[os.path.realpath(link)] = link
    return aliases


def same_port(a: str | None, b: str | None) -> bool:
    """True if two port names refer to the same device (follows by-id symlinks)."""
    if not a or not b:
        return False
    if _is_posix_device_path(a) and _is_posix_device_path(b):
        return os.path.realpath(a) == os.path.realpath(b)
    return a.lower() == b.lower()


def list_ports() -> list[PortStatus]:
    aliases = by_id_aliases()
    return [
        PortStatus(path, os.access(path, os.R_OK | os.W_OK), aliases.get(path))
        for path in candidate_ports()
    ]


def _present_ports_hint() -> str:
    present = candidate_ports()
    if present:
        return "serial ports present right now: " + ", ".join(present)
    return (
        "no USB serial ports are present. Is the board plugged in and switched on?\n"
        "Some USB cables are charge-only; try another cable or port."
    )


def permission_hint(port: str, st: os.stat_result | None = None) -> str:
    """Explain who may open ``port`` and the exact command that grants access."""
    if not _is_posix_device_path(port):
        return "close any other program using the port and try again"
    import grp
    import pwd

    st = st or os.stat(port)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner = str(st.st_uid)
    user = pwd.getpwuid(os.getuid()).pw_name
    mode = stat.filemode(st.st_mode)

    in_group_db = False
    try:
        entry = grp.getgrgid(st.st_gid)
        in_group_db = user in entry.gr_mem or pwd.getpwnam(user).pw_gid == st.st_gid
    except KeyError:
        pass

    lines = [f"{port} is {mode} {owner}:{group}; your user '{user}' can't read/write it."]
    if in_group_db and st.st_gid not in os.getgroups():
        lines.append(
            f"You are already in group '{group}', but this login session started before that."
        )
        lines.append(f"fix: log out and back in (or run `newgrp {group}` in this terminal)")
    else:
        lines.append(f"fix: sudo usermod -aG {group} $USER    # then log out and back in")
    lines.append(f"one-off, until the board is replugged: sudo chmod a+rw {port}")
    return "\n".join(lines)


def check_port(port: str) -> None:
    """Raise ``PortProblem`` if ``port`` is missing, not a tty, or not readable/writable."""
    if not _is_posix_device_path(port):
        return
    if not os.path.exists(port):
        if os.path.lexists(port):
            raise PortProblem(
                f"{port} is a dangling link (the board was probably unplugged)",
                _present_ports_hint(),
            )
        raise PortProblem(f"{port} does not exist", _present_ports_hint())
    st = os.stat(port)
    if not stat.S_ISCHR(st.st_mode):
        kind = "directory" if stat.S_ISDIR(st.st_mode) else "regular file"
        raise PortProblem(
            f"{port} is a {kind}, not a serial device",
            "pass the board's tty, e.g. /dev/ttyACM0 (run `builderwars ports` to list them)",
        )
    if not os.access(port, os.R_OK | os.W_OK):
        raise PortProblem(f"permission denied opening {port}", permission_hint(port, st))


_BUSY = ("busy", "errno 16", "errno 11", "exclusively lock", "resource temporarily unavailable")


def is_busy_error(error: str) -> bool:
    """The port exists but another process has it open (pyserial's exclusive lock)."""
    text = error.lower()
    return any(marker in text for marker in _BUSY)


def port_in_error(error: str) -> str | None:
    """The tty an error message names, e.g. "... lock port /dev/ttyACM2: ..." -> /dev/ttyACM2."""
    match = re.search(r"(/dev/[\w./-]+?)(?=[:\s,)]|$)", error)
    return match.group(1) if match else None


def holders(port: str) -> list[tuple[int, str]]:
    """Processes that have ``port`` open, as ``(pid, command line)`` (Linux, best effort:
    only processes this user may inspect are seen)."""
    if not sys.platform.startswith("linux") or not _is_posix_device_path(port):
        return []
    target = os.path.realpath(port)
    found: list[tuple[int, str]] = []
    for fd_dir in glob.glob("/proc/[0-9]*/fd"):
        pid = int(fd_dir.split("/")[2])
        if pid == os.getpid():
            continue
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(f"{fd_dir}/{fd}") == target:
                    break
            except OSError:
                continue
        else:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                cmd = fh.read().replace(b"\0", b" ").decode(errors="replace").strip()
        except OSError:
            cmd = "?"
        found.append((pid, cmd[:160] or "?"))
    return found


def busy_hint(port: str | None) -> str:
    """Who has the port, and how to free it."""
    lines: list[str] = []
    who = holders(port) if port else []
    if who:
        lines.append(f"{port} is open in:")
        lines += [f"  pid {pid}: {cmd}" for pid, cmd in who]
        if any("builderwars" in cmd or "board_runtime" in cmd for _, cmd in who):
            lines.append(
                "that is another builderwars on this laptop: stop it (Ctrl+C there, or "
                f"`kill {who[0][0]}`), then retry"
            )
        else:
            lines.append(f"close that program (or `kill {who[0][0]}`), then retry")
    else:
        lines.append(
            "another program has the port open: another `builderwars run`/`test`/`sensors "
            "--read`, screen, minicom or the FREE-WILi desktop app"
            + (f" (`fuser -v {port}` shows which)" if port else "")
        )
        if sys.platform.startswith("linux"):
            lines.append(
                "right after plugging in, ModemManager probes /dev/ttyACM* for a few seconds; "
                "if it keeps happening: sudo systemctl stop ModemManager"
            )
    return "\n".join(lines)


def open_error_hint(port: str | None, error: str) -> str:
    """Best-guess fix for an error string returned when opening a serial port."""
    text = error.lower()
    port = port_in_error(error) or port
    if "permission" in text or "errno 13" in text:
        return permission_hint(port) if port else "check the serial port permissions"
    if is_busy_error(error):
        return busy_hint(port)
    if "no such file" in text or "errno 2" in text:
        return "the port disappeared while opening; the board was probably unplugged or reset"
    return (
        "the board didn't answer. Unplug it, wait ~5 s, plug it back in and retry.\n"
        "On Linux, ModemManager can grab /dev/ttyACM* ports: sudo systemctl stop ModemManager"
    )
