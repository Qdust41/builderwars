"""Ports for auto-fix (LLM-proposed pull requests for device errors, ADR 0012)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from domain.autofix import AutoFixRun, AutoFixSettings


class AutoFixSettingsRepository(Protocol):
    def get(self, project_id: str) -> AutoFixSettings | None: ...
    def save(self, settings: AutoFixSettings) -> None: ...
    def delete(self, project_id: str) -> None: ...


class AutoFixRunRepository(Protocol):
    def add(self, run: AutoFixRun) -> None: ...
    def save(self, run: AutoFixRun) -> None: ...
    def get(self, run_id: str) -> AutoFixRun | None: ...
    def list_for_project(self, project_id: str, *, limit: int) -> list[AutoFixRun]:
        """Newest first."""
        ...

    def count_since(self, project_id: str, since: datetime) -> int:
        """Runs created for the project at or after ``since`` (the daily cap)."""
        ...

    def claim_signature(
        self, project_id: str, signature: str, *, now: datetime, window: timedelta
    ) -> bool:
        """Atomically record that ``signature`` starts a run now. False when it already
        started one within ``window`` (so the same error does not open a PR again)."""
        ...


@dataclass(frozen=True, slots=True)
class LlmConfig:
    """The app-wide model: one OpenAI-compatible endpoint for every project (set at deploy time
    from GitHub Actions variables and the ``AUTOFIX_LLM_API_KEY`` secret)."""

    base_url: str
    model: str
    api_key: str | None = field(default=None, repr=False)


class AutoFixQueue(Protocol):
    """Hands a run to the auto-fix worker (SQS in AWS). Messages carry only the run id."""

    def enqueue_autofix(self, run_id: str) -> None: ...
