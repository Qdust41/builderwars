"""OpenAI-compatible Chat Completions client — STUB.

TODO (spec 08):
* POST ``{endpoint}/chat/completions`` with ``model``, ``messages`` and ``tools`` (JSON schemas
  from ``ToolRegistry``); parse ``tool_calls`` into ``ToolCallRequest`` and pass every one
  through ``ToolCallGate`` — the model never executes anything directly.
* ``openai_compatible``: bearer API key fetched from Secrets Manager at cold start.
* ``bedrock``: sign requests with SigV4 (service ``bedrock``) using the worker role.
* Run ``context.redact`` on everything before it leaves; record tokens/cost on the ``AiRun``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ai_platform.providers.config import ProviderConfig


class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def complete(
        self, *, system: str, messages: Sequence[dict[str, Any]], tools: Sequence[str]
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{self.config.mode.value} provider client is not implemented yet (spec 08)"
        )
