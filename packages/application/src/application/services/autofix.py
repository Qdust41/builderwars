"""Auto-fix settings, the error-log trigger, and manual fix requests (ADR 0012).

* ``AutoFixService``: owners/admins link an OpenAI-compatible endpoint and a GitHub repository
  to a project; members ask for a fix of a specific error and see past runs.
* ``AutoFixTrigger``: called by device ingest for every new error/critical log line or error
  event. It starts a run only when the project turned auto-fix on, the same error has not
  started one within the dedupe window, and the project is under its daily cap. It never
  raises: a failure here must not lose the device data being ingested.

The fix itself (LLM + GitHub) runs in the auto-fix worker (``ai_platform.autofix``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from application.ports import (
    AutoFixQueue,
    AutoFixRunRepository,
    AutoFixSecrets,
    AutoFixSecretStore,
    AutoFixSettingsRepository,
    DeviceRepository,
    TelemetryRepository,
)
from application.services.authorization import Authorizer
from domain.autofix import (
    BRANCH_PATTERN,
    DEFAULT_DEDUPE_HOURS,
    DEFAULT_MAX_RUNS_PER_DAY,
    GITHUB_REPO_PATTERN,
    AutoFixLevel,
    AutoFixRun,
    AutoFixSettings,
    AutoFixTriggerKind,
    error_signature,
)
from domain.common import ConflictError, DomainError, NotFoundError, utcnow
from domain.projects import Permission

log = logging.getLogger(__name__)

MAX_RUNS_LISTED = 50
MAX_ERROR_MESSAGE = 4096


class AutoFixValidationError(DomainError):
    """Settings the API should reject with 422."""


class AutoFixNotReadyError(ConflictError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.code = "autofix_not_ready"


class AutoFixLimitError(ConflictError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.code = "autofix_daily_limit"


@dataclass(frozen=True, slots=True)
class AutoFixSettingsInput:
    """What an owner/admin sends. For each secret: ``None`` keeps the stored value, ``""``
    clears it, anything else replaces it."""

    llm_base_url: str
    llm_model: str
    github_repo: str
    enabled: bool = True
    auto_trigger: bool = True
    min_level: AutoFixLevel = AutoFixLevel.ERROR
    base_branch: str | None = None
    max_runs_per_day: int = DEFAULT_MAX_RUNS_PER_DAY
    dedupe_hours: int = DEFAULT_DEDUPE_HOURS
    instructions: str | None = None
    llm_api_key: str | None = None
    github_token: str | None = None


def _validate(data: AutoFixSettingsInput) -> None:
    url = urlsplit(data.llm_base_url)
    if url.scheme not in {"http", "https"} or not url.hostname:
        raise AutoFixValidationError("llm_base_url must be an http(s) URL")
    if url.username or url.password:
        raise AutoFixValidationError("put the API key in llm_api_key, not in the URL")
    if not data.llm_model.strip():
        raise AutoFixValidationError("llm_model is required")
    if not GITHUB_REPO_PATTERN.match(data.github_repo):
        raise AutoFixValidationError("github_repo must look like owner/name")
    if data.base_branch is not None and not BRANCH_PATTERN.match(data.base_branch):
        raise AutoFixValidationError("base_branch is not a valid branch name")
    if not 1 <= data.max_runs_per_day <= 50:
        raise AutoFixValidationError("max_runs_per_day must be between 1 and 50")
    if not 1 <= data.dedupe_hours <= 24 * 30:
        raise AutoFixValidationError("dedupe_hours must be between 1 and 720")


def _merge(stored: str | None, update: str | None) -> str | None:
    if update is None:
        return stored
    return update or None


class AutoFixService:
    def __init__(
        self,
        *,
        settings: AutoFixSettingsRepository,
        runs: AutoFixRunRepository,
        secrets: AutoFixSecretStore,
        queue: AutoFixQueue,
        devices: DeviceRepository,
        telemetry: TelemetryRepository,
        authorizer: Authorizer,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._settings = settings
        self._runs = runs
        self._secrets = secrets
        self._queue = queue
        self._devices = devices
        self._telemetry = telemetry
        self._authorizer = authorizer
        self._clock = clock

    # --- settings (owner/admin) ---------------------------------------------------------------

    def get_settings(self, *, user_id: str, project_id: str) -> AutoFixSettings | None:
        self._authorizer.require(user_id, project_id, Permission.VIEW_PROJECT)
        return self._settings.get(project_id)

    def save_settings(
        self, *, user_id: str, project_id: str, data: AutoFixSettingsInput
    ) -> AutoFixSettings:
        self._authorizer.require(user_id, project_id, Permission.MANAGE_PROJECT)
        _validate(data)
        existing = self._settings.get(project_id)
        secrets = self._secrets.get(project_id) if existing else AutoFixSecrets()
        if data.llm_api_key is not None or data.github_token is not None:
            secrets = AutoFixSecrets(
                llm_api_key=_merge(secrets.llm_api_key, data.llm_api_key),
                github_token=_merge(secrets.github_token, data.github_token),
            )
            self._secrets.put(project_id, secrets)
        settings = AutoFixSettings(
            project_id=project_id,
            llm_base_url=data.llm_base_url.rstrip("/"),
            llm_model=data.llm_model.strip(),
            github_repo=data.github_repo,
            updated_by=user_id,
            enabled=data.enabled,
            auto_trigger=data.auto_trigger,
            min_level=data.min_level,
            base_branch=data.base_branch or None,
            max_runs_per_day=data.max_runs_per_day,
            dedupe_hours=data.dedupe_hours,
            instructions=(data.instructions or "").strip() or None,
            has_llm_api_key=secrets.llm_api_key is not None,
            has_github_token=secrets.github_token is not None,
            updated_at=self._clock(),
        )
        self._settings.save(settings)
        return settings

    def delete_settings(self, *, user_id: str, project_id: str) -> None:
        """Unlink the endpoint and repository and delete the stored keys. Past runs stay."""
        self._authorizer.require(user_id, project_id, Permission.MANAGE_PROJECT)
        self._secrets.delete(project_id)
        self._settings.delete(project_id)

    # --- runs ---------------------------------------------------------------------------------

    def request_fix(
        self,
        *,
        user_id: str,
        project_id: str,
        device_id: str | None,
        message: str | None,
        level: str = "error",
    ) -> AutoFixRun:
        """Start a run now for one error. Skips the dedupe window, not the daily cap.

        With no ``message``, the device's most recent error/critical log line is used.
        """
        self._authorizer.require(user_id, project_id, Permission.RUN_AI)
        if device_id is not None:
            device = self._devices.get(device_id)
            if device is None or device.project_id != project_id:
                raise NotFoundError("device", device_id)
        settings = self._settings.get(project_id)
        if settings is None or not settings.enabled:
            raise AutoFixNotReadyError("auto-fix is not set up or not enabled for this project")
        if not message:
            if device_id is None:
                raise AutoFixValidationError("give a message or a device_id to take it from")
            found = self._latest_error(device_id)
            if found is None:
                raise AutoFixValidationError("this device has no recent error to fix")
            level, message = found
        now = self._clock()
        if self._runs.count_since(project_id, now - timedelta(days=1)) >= (
            settings.max_runs_per_day
        ):
            raise AutoFixLimitError(
                f"this project already started {settings.max_runs_per_day} auto-fix runs "
                "in the last 24 hours"
            )
        signature = error_signature(message)
        self._runs.claim_signature(
            project_id, signature, now=now, window=timedelta(0)
        )  # resets the dedupe window, so the automatic trigger does not repeat this run
        return _start(
            self._runs,
            self._queue,
            AutoFixRun(
                project_id=project_id,
                trigger=AutoFixTriggerKind.MANUAL,
                signature=signature,
                error_level=level,
                error_message=message[:MAX_ERROR_MESSAGE],
                device_id=device_id,
                requested_by=user_id,
                created_at=now,
            ),
        )

    def list_runs(self, *, user_id: str, project_id: str) -> list[AutoFixRun]:
        self._authorizer.require(user_id, project_id, Permission.VIEW_PROJECT)
        return self._runs.list_for_project(project_id, limit=MAX_RUNS_LISTED)

    def get_run(self, *, user_id: str, project_id: str, run_id: str) -> AutoFixRun:
        self._authorizer.require(user_id, project_id, Permission.VIEW_PROJECT)
        run = self._runs.get(run_id)
        if run is None or run.project_id != project_id:
            raise NotFoundError("auto-fix run", run_id)
        return run

    def _latest_error(self, device_id: str) -> tuple[str, str] | None:
        for entry in reversed(self._telemetry.recent_logs(device_id, limit=200)):
            if entry.level in {"error", "critical"}:
                return entry.level, entry.message
        return None


def _start(runs: AutoFixRunRepository, queue: AutoFixQueue, run: AutoFixRun) -> AutoFixRun:
    # Persist first, then enqueue: the worker that receives the id can always load the run.
    runs.add(run)
    queue.enqueue_autofix(run.id)
    return run


class AutoFixTrigger:
    """Starts runs from ingested device errors. Plug into ``DeviceMessageIngestService``."""

    def __init__(
        self,
        *,
        settings: AutoFixSettingsRepository,
        runs: AutoFixRunRepository,
        queue: AutoFixQueue,
        devices: DeviceRepository,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._settings = settings
        self._runs = runs
        self._queue = queue
        self._devices = devices
        self._clock = clock

    def on_device_error(self, *, device_id: str, level: str, message: str) -> AutoFixRun | None:
        try:
            return self._maybe_start(device_id=device_id, level=level, message=message)
        except Exception:
            log.exception("auto-fix trigger failed for device %s; ingest continues", device_id)
            return None

    def _maybe_start(self, *, device_id: str, level: str, message: str) -> AutoFixRun | None:
        device = self._devices.get(device_id)
        if device is None:
            return None
        settings = self._settings.get(device.project_id)
        if (
            settings is None
            or not settings.enabled
            or not settings.auto_trigger
            or not settings.min_level.matches(level)
        ):
            return None
        now = self._clock()
        if self._runs.count_since(device.project_id, now - timedelta(days=1)) >= (
            settings.max_runs_per_day
        ):
            log.info("auto-fix daily cap reached for project %s", device.project_id)
            return None
        signature = error_signature(message)
        if not self._runs.claim_signature(
            device.project_id,
            signature,
            now=now,
            window=timedelta(hours=settings.dedupe_hours),
        ):
            return None
        return _start(
            self._runs,
            self._queue,
            AutoFixRun(
                project_id=device.project_id,
                trigger=AutoFixTriggerKind.ERROR_LOG,
                signature=signature,
                error_level=level,
                error_message=message[:MAX_ERROR_MESSAGE],
                device_id=device_id,
                created_at=now,
            ),
        )
