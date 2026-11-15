"""Auto-fix: the app-wide model settings and the auto-fix run queue (ADR 0012).

The model (base URL, name) comes from the worker's environment; its API key from one secret,
``{"llm_api_key": ...}``, that the Workers stack creates and the deploy fills from the
``AUTOFIX_LLM_API_KEY`` GitHub Actions secret. Only the auto-fix worker can read it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from application.ports import LlmConfig


def llm_config_loader(
    *, base_url: str | None, model: str | None, client: Any = None, secret_id: str | None = None
) -> Callable[[], LlmConfig | None]:
    """``None`` from the loader means "no model configured". The key is read on every run, so
    a rotated key is picked up without restarting the worker."""

    def load() -> LlmConfig | None:
        if not base_url or not model:
            return None
        api_key = None
        if client is not None and secret_id:
            response = client.get_secret_value(SecretId=secret_id)
            api_key = json.loads(response.get("SecretString") or "{}").get("llm_api_key") or None
        return LlmConfig(base_url=base_url, model=model, api_key=api_key)

    return load


class SqsAutoFixQueue:
    def __init__(self, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def enqueue_autofix(self, run_id: str) -> None:
        self._client.send_message(
            QueueUrl=self._queue_url, MessageBody=json.dumps({"run_id": run_id})
        )
