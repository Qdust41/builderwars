"""Host-side firmware update helpers (decision #9). Nothing here runs automatically.

Flow (spec 09): job -> host downloads ``_main.uf2`` from S3 over TLS -> verify sha256 against
the artifact record -> write the UF2 to both RP2040s over USB -> report the result. The
checksum always comes from the cloud's artifact record, never from a file on the host.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import Protocol


class ChecksumMismatchError(Exception):
    pass


def sha256_of(path: Path, chunk_size: int = 1 << 16) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected: str) -> None:
    """Raise unless ``path`` hashes to ``expected``; call before any flashing."""
    actual = sha256_of(path)
    if not hmac.compare_digest(actual, expected.lower()):
        raise ChecksumMismatchError(f"{path.name}: expected {expected}, got {actual}")


class Uf2Flasher(Protocol):
    def flash(self, uf2_path: Path) -> None:
        """Write a verified ``_main.uf2`` to both CPUs of the attached board."""
        ...


class FreeWiliUf2Flasher:
    """STUB. TODO (spec 09): reproduce fwOGAppExplorer's dual-CPU UF2 write via the
    ``freewili`` package (``reset_to_uf2_bootloader`` per processor, then copy the UF2), and
    report which CPU succeeded. Requires the host to be online and the board USB-connected.
    """

    def flash(self, uf2_path: Path) -> None:
        raise NotImplementedError("UF2 flashing is not implemented yet")
