"""Serial-port preflight checks that turn "it doesn't work" into a specific cause + fix.

Pure stdlib, no ``freewili`` import, so it works (and is testable) without the vendor package.
Checks only run for POSIX device paths (``/dev/...``); Windows ``COMx`` names are passed through.
"""

from __future__ import annotations

import glob
import os
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


def open_error_hint(port: str | None, error: str) -> str:
    """Best-guess fix for an error string returned when opening a serial port."""
    text = error.lower()
    if "permission" in text or "errno 13" in text:
        return permission_hint(port) if port else "check the serial port permissions"
    if "busy" in text or "errno 16" in text:
        who = f"`fuser -v {port}` shows who has it" if port else "close other serial programs"
        return (
            "another program has the port open (screen, minicom, a FREE-WILi app, another "
            f"builderwars run); {who}"
        )
    if "no such file" in text or "errno 2" in text:
        return "the port disappeared while opening; the board was probably unplugged or reset"
    return (
        "the board didn't answer. Unplug it, wait ~5 s, plug it back in and retry.\n"
        "On Linux, ModemManager can grab /dev/ttyACM* ports: sudo systemctl stop ModemManager"
    )
