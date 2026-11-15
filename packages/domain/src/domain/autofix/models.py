"""Auto-fix: when a board reports an error, ask an LLM for a fix and open a pull request.

The model is app-wide: one OpenAI-compatible endpoint (base URL, model, API key) set at deploy
time from GitHub Actions variables and a secret. The git side is per project: an owner/admin
links a GitHub repository (``owner/name``, token, optional base branch), stored in the
``autofix_settings`` table for the MVP (ADR 0012). The API never returns the token.

A run is one attempt to fix one error. It ends in exactly one of:

* ``pr_opened``: a branch and pull request exist on the linked repository (never merged here);
* ``no_fix``: the model looked and did not propose a change it was confident in;
* ``failed``: something broke (endpoint unreachable, bad token, unusable answer).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Final

from domain.common import InvalidStateTransitionError, new_id, utcnow

GITHUB_REPO_PATTERN: Final = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$"
)
# Branch names GitHub accepts that are also safe to put in a URL path.
BRANCH_PATTERN: Final = re.compile(r"^(?!/)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}(?<!/)(?<!\.)$")

DEFAULT_MAX_RUNS_PER_DAY: Final = 5
DEFAULT_DEDUPE_HOURS: Final = 24


class AutoFixLevel(StrEnum):
    """The lowest log level that starts a run automatically."""

    ERROR = "error"
    CRITICAL = "critical"

    def matches(self, level: str) -> bool:
        level = level.lower()
        if self is AutoFixLevel.CRITICAL:
            return level == "critical"
        return level in {"error", "critical"}


@dataclass(frozen=True, slots=True)
class AutoFixSettings:
    project_id: str
    github_repo: str  # owner/name
    updated_by: str
    enabled: bool = True
    # True: error logs start runs on their own. False: only the manual "fix this" call does.
    auto_trigger: bool = True
    min_level: AutoFixLevel = AutoFixLevel.ERROR
    base_branch: str | None = None  # None = the repository's default branch
    max_runs_per_day: int = DEFAULT_MAX_RUNS_PER_DAY
    dedupe_hours: int = DEFAULT_DEDUPE_HOURS
    # Free text handed to the model, e.g. "board code is in scripts/wili_code".
    instructions: str | None = None
    # Write-only through the API; repr=False keeps it out of logs and tracebacks.
    github_token: str | None = field(default=None, repr=False)
    updated_at: datetime = field(default_factory=utcnow)

    @property
    def has_github_token(self) -> bool:
        return bool(self.github_token)

    @property
    def ready(self) -> bool:
        """Turned on and able to open pull requests."""
        return self.enabled and self.has_github_token


class AutoFixRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PR_OPENED = "pr_opened"
    NO_FIX = "no_fix"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL


_TERMINAL: Final = frozenset(
    {AutoFixRunStatus.PR_OPENED, AutoFixRunStatus.NO_FIX, AutoFixRunStatus.FAILED}
)


class AutoFixTriggerKind(StrEnum):
    ERROR_LOG = "error_log"  # an uploaded error/critical log line or error event
    MANUAL = "manual"  # someone asked for it through the API


_ALLOWED: Final[dict[AutoFixRunStatus, frozenset[AutoFixRunStatus]]] = {
    AutoFixRunStatus.QUEUED: frozenset({AutoFixRunStatus.RUNNING, AutoFixRunStatus.FAILED}),
    AutoFixRunStatus.RUNNING: frozenset(
        {AutoFixRunStatus.PR_OPENED, AutoFixRunStatus.NO_FIX, AutoFixRunStatus.FAILED}
    ),
    AutoFixRunStatus.PR_OPENED: frozenset(),
    AutoFixRunStatus.NO_FIX: frozenset(),
    AutoFixRunStatus.FAILED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class AutoFixRun:
    project_id: str
    trigger: AutoFixTriggerKind
    signature: str
    error_level: str
    error_message: str
    id: str = field(default_factory=lambda: new_id("fix"))
    device_id: str | None = None
    requested_by: str | None = None  # None when an uploaded error started it
    status: AutoFixRunStatus = AutoFixRunStatus.QUEUED
    created_at: datetime = field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    model: str | None = None
    github_repo: str | None = None
    branch: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    # The model's explanation (pr_opened / no_fix) or what went wrong (failed).
    summary: str | None = None
    files_changed: tuple[str, ...] = ()

    def transition(self, new_status: AutoFixRunStatus, **changes: object) -> AutoFixRun:
        if new_status not in _ALLOWED[self.status]:
            raise InvalidStateTransitionError(
                f"auto-fix run {self.id}: {self.status.value} -> {new_status.value} not allowed"
            )
        now = utcnow()
        return replace(
            self,
            status=new_status,
            started_at=now if new_status is AutoFixRunStatus.RUNNING else self.started_at,
            completed_at=now if new_status.is_terminal else self.completed_at,
            **changes,  # type: ignore[arg-type]
        )


_HEX = re.compile(r"\b0x[0-9a-f]+\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_QUOTED = re.compile(r"(['\"]).*?\1")
_SPACE = re.compile(r"\s+")


def normalize_error(message: str) -> str:
    """The parts of an error message that stay the same each time it happens.

    Numbers, hex values, UUIDs and quoted values are replaced, so "timeout after 503 ms on
    'COM3'" and "timeout after 498 ms on 'COM4'" count as the same error.
    """
    text = message.strip().lower()
    text = _UUID.sub("<id>", text)
    text = _HEX.sub("<hex>", text)
    text = _QUOTED.sub("<str>", text)
    text = _NUMBER.sub("<n>", text)
    return _SPACE.sub(" ", text)[:500]


def error_signature(message: str) -> str:
    """Stable id for "the same error" within a project (dedupe key)."""
    return hashlib.sha256(normalize_error(message).encode()).hexdigest()[:32]
