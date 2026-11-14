"""AI provider configuration (decision #8).

One wire protocol for every provider: the OpenAI-compatible Chat Completions API. Two auth
modes:

* ``openai_compatible`` — any ``AI_BASE_URL`` + API key (OpenAI, Azure OpenAI, Ollama, LM
  Studio...). The key lives in Secrets Manager; config holds only its ARN/name.
* ``bedrock`` — Amazon Bedrock's OpenAI-compatible endpoint in ``AI_REGION``, signed with
  SigV4 from the worker's IAM role. No API key; data stays inside the AWS boundary.

The default model name is chosen in spec 08, so ``AI_MODEL`` has no default.
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ProviderMode(StrEnum):
    OPENAI_COMPATIBLE = "openai_compatible"
    BEDROCK = "bedrock"


class ProviderConfigError(ValueError):
    pass


def bedrock_base_url(region: str) -> str:
    # TODO (spec 08): confirm the path against current Bedrock docs before first use.
    return f"https://bedrock-runtime.{region}.amazonaws.com/openai/v1"


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: ProviderMode
    model: str = Field(min_length=1, max_length=200)
    base_url: HttpUrl | None = None
    api_key_secret_id: str | None = None  # Secrets Manager ARN/name, never the key itself
    region: str = "us-east-1"

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.mode is ProviderMode.OPENAI_COMPATIBLE:
            if self.base_url is None:
                raise ValueError("openai_compatible mode requires base_url")
        elif self.api_key_secret_id is not None:
            raise ValueError("bedrock mode authenticates with IAM; do not set an API key")
        return self

    @property
    def endpoint(self) -> str:
        if self.mode is ProviderMode.BEDROCK:
            return bedrock_base_url(self.region)
        return str(self.base_url).rstrip("/")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> ProviderConfig:
        e = dict(os.environ if env is None else env)
        if not e.get("AI_MODEL"):
            raise ProviderConfigError("AI_MODEL is required (chosen in spec 08)")
        try:
            return cls(
                mode=ProviderMode(e.get("AI_PROVIDER", ProviderMode.OPENAI_COMPATIBLE)),
                model=e["AI_MODEL"],
                base_url=e.get("AI_BASE_URL") or None,
                api_key_secret_id=e.get("AI_API_KEY_SECRET_ID") or None,
                region=e.get("AI_REGION", "us-east-1"),
            )
        except ValueError as exc:
            raise ProviderConfigError(str(exc)) from exc
