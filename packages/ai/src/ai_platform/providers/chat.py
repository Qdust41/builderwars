"""A plain OpenAI-compatible Chat Completions call (``POST {base_url}/chat/completions``).

Works with OpenAI, Azure OpenAI's v1 endpoint, OpenRouter, Together, Groq, vLLM, Ollama, LM
Studio and anything else that speaks the same API. ``base_url`` is the part before
``/chat/completions`` (usually ending in ``/v1``).
"""

from __future__ import annotations

from collections.abc import Sequence

from ai_platform.http import HttpError, HttpTransport, UrllibTransport, send_json


class ChatCompletionsClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        transport: HttpTransport | None = None,
        timeout: float = 120.0,
        temperature: float = 0.1,
        max_tokens: int = 8000,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._transport = transport or UrllibTransport()
        self._timeout = timeout
        self._temperature = temperature
        self._max_tokens = max_tokens

    def complete(self, messages: Sequence[dict[str, str]]) -> str:
        headers = {"User-Agent": "builderwars-autofix"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        response = send_json(
            self._transport,
            "POST",
            f"{self.base_url}/chat/completions",
            headers=headers,
            payload={
                "model": self.model,
                "messages": list(messages),
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
            },
            timeout=self._timeout,
        )
        if response.status >= 400:
            raise HttpError(
                f"LLM endpoint returned HTTP {response.status}: {_error_text(response.body)}",
                status=response.status,
            )
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise HttpError("LLM endpoint returned no choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise HttpError("LLM endpoint returned an empty answer")
        return content


def _error_text(body: bytes) -> str:
    text = body.decode("utf-8", "replace").strip()
    return text[:300] or "(empty body)"
