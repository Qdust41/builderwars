"""LOCAL ONLY: run auto-fix in a background thread of the API process instead of a Lambda.

Lets someone try auto-fix end to end with ``uvicorn`` and a local model (Ollama, LM Studio):
private/localhost endpoints are allowed here and nowhere else.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from ai_platform.autofix import AutoFixWorker, default_clients
from application.ports import (
    AutoFixRunRepository,
    AutoFixSecrets,
    AutoFixSecretStore,
    AutoFixSettingsRepository,
    TelemetryRepository,
)

log = logging.getLogger(__name__)


@dataclass
class ThreadedAutoFixQueue:
    worker: AutoFixWorker

    @classmethod
    def for_local(
        cls,
        *,
        runs: AutoFixRunRepository,
        settings: AutoFixSettingsRepository,
        secrets: AutoFixSecretStore,
        telemetry: TelemetryRepository,
        shared_github_token: str | None = None,
    ) -> ThreadedAutoFixQueue:
        shared = AutoFixSecrets(github_token=shared_github_token)
        return cls(
            AutoFixWorker(
                runs=runs,
                settings=settings,
                secrets=secrets,
                telemetry=telemetry,
                clients=default_clients(allow_private_endpoints=True),
                shared=lambda: shared,
            )
        )

    def enqueue_autofix(self, run_id: str) -> None:
        threading.Thread(
            target=self._run, args=(run_id,), name=f"autofix-{run_id}", daemon=True
        ).start()

    def _run(self, run_id: str) -> None:
        try:
            self.worker.handle(run_id)
        except Exception:
            log.exception("local auto-fix run %s crashed", run_id)
