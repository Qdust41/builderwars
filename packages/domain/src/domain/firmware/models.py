"""Firmware / board-runtime artifact references.

Model only. Building, signing and deploying firmware are out of scope for the scaffold
(docs/open-decisions.md #9). Nothing in this codebase flashes or deploys firmware.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from domain.common import new_id, utcnow

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FirmwareArtifactState(StrEnum):
    BUILT = "built"  # produced by a build job, not yet reviewed
    APPROVED = "approved"  # a human reviewed it; eligible for a future deployment job
    REJECTED = "rejected"
    REVOKED = "revoked"  # withdrawn after approval (e.g. found faulty)


@dataclass(frozen=True, slots=True)
class ArtifactLocation:
    """Where the immutable artifact bytes live (an S3 bucket/key in AWS)."""

    bucket: str
    key: str


@dataclass(frozen=True, slots=True)
class FirmwareArtifact:
    project_id: str
    version: str
    checksum_sha256: str
    location: ArtifactLocation
    compatible_hardware_models: frozenset[str]
    build_job_id: str | None = None
    state: FirmwareArtifactState = FirmwareArtifactState.BUILT
    signature_reference: str | None = None  # TODO: signing scheme is an open decision
    id: str = field(default_factory=lambda: new_id("fw"))
    created_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if not _SHA256_RE.fullmatch(self.checksum_sha256):
            raise ValueError("checksum_sha256 must be 64 lowercase hex characters")
        if not self.compatible_hardware_models:
            raise ValueError("an artifact must declare at least one compatible hardware model")

    def is_compatible_with(self, hardware_model: str) -> bool:
        return hardware_model in self.compatible_hardware_models
