"""LOCAL ONLY: run auto-fix in a background thread of the API process instead of a Lambda.

Lets someone try auto-fix end to end with ``uvicorn`` and a local model (Ollama, LM Studio):
private/localhost endpoints are allowed here and nowhere else. The model comes from
AUTOFIX_LLM_BASE_URL / AUTOFIX_LLM_MODEL / AUTOFIX_LLM_API_KEY in the API's environment.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from ai_platform.autofix import AutoFixWorker, default_clients
from application.ports import (
    AutoFixRunRepository,
    AutoFixSettingsRepository,
    LlmConfig,
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
        telemetry: TelemetryRepository,
        llm: LlmConfig | None,
    ) -> ThreadedAutoFixQueue:
        return cls(
            AutoFixWorker(
                runs=runs,
                settings=settings,
                telemetry=telemetry,
                clients=default_clients(allow_private_endpoints=True),
                llm=lambda: llm,
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
