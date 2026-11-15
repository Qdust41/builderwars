"""Build the LLM and GitHub clients for one run: the app-wide model and the project's repo."""

from __future__ import annotations

from ai_platform.autofix.agent import ChatModel, ClientFactory, CodeHost
from ai_platform.autofix.github import GitHubRepository
from ai_platform.http import HttpError, ensure_public_endpoint
from ai_platform.providers.chat import ChatCompletionsClient
from application.ports import LlmConfig
from domain.autofix import AutoFixSettings


def default_clients(*, allow_private_endpoints: bool = False) -> ClientFactory:
    """``allow_private_endpoints``: local development only (a local Ollama on localhost)."""

    def build(settings: AutoFixSettings, llm: LlmConfig) -> tuple[ChatModel, CodeHost]:
        if not settings.github_token:
            raise HttpError("this project has no GitHub token")
        if not allow_private_endpoints:
            ensure_public_endpoint(llm.base_url)
        chat = ChatCompletionsClient(
            base_url=llm.base_url, model=llm.model, api_key=llm.api_key, timeout=180.0
        )
        return chat, GitHubRepository(settings.github_repo, settings.github_token)

    return build
