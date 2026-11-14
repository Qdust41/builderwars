"""Schema versioning for device messages.

Every envelope carries an integer ``schema_version``. The cloud accepts any version listed in
``SUPPORTED_SCHEMA_VERSIONS`` and rejects everything else with a distinct error, so that a board
running newer firmware than the cloud understands fails loudly instead of being half-parsed.

Rules for evolving the protocol (see docs/device-protocol.md):

* Adding an optional field to a payload does not need a new version.
* Removing/renaming a field, changing a type, or changing semantics needs a new version.
* The cloud should support at least the previous version while boards are upgraded.
"""

from __future__ import annotations

from typing import Final

CURRENT_SCHEMA_VERSION: Final[int] = 1
SUPPORTED_SCHEMA_VERSIONS: Final[frozenset[int]] = frozenset({1})


class UnsupportedSchemaVersionError(ValueError):
    """Raised when a message declares a schema version this code does not understand."""

    def __init__(self, version: object) -> None:
        supported = ", ".join(str(v) for v in sorted(SUPPORTED_SCHEMA_VERSIONS))
        super().__init__(f"unsupported schema_version {version!r}; supported: {supported}")
        self.version = version


def is_supported(version: int) -> bool:
    return version in SUPPORTED_SCHEMA_VERSIONS


def ensure_supported(version: int) -> int:
    if not is_supported(version):
        raise UnsupportedSchemaVersionError(version)
    return version
