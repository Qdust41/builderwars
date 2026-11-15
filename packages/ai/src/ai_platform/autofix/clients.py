"""Build the LLM and GitHub clients for one run from a project's settings and keys."""

from __future__ import annotations

from ai_platform.autofix.agent import ChatModel, ClientFactory, CodeHost
from ai_platform.autofix.github import GitHubRepository
from ai_platform.http import HttpError, ensure_public_endpoint
from ai_platform.providers.chat import ChatCompletionsClient
from application.ports import AutoFixSecrets
from domain.autofix import AutoFixSettings


def default_clients(*, allow_private_endpoints: bool = False) -> ClientFactory:
    """``allow_private_endpoints``: local development only (a local Ollama on localhost)."""

    def build(settings: AutoFixSettings, secrets: AutoFixSecrets) -> tuple[ChatModel, CodeHost]:
        if not secrets.github_token:
            raise HttpError(
                "no GitHub token: set the AUTOFIX_GITHUB_TOKEN repository secret and redeploy, "
                "or give this project its own token"
            )
        if not allow_private_endpoints:
            ensure_public_endpoint(settings.llm_base_url)
        chat = ChatCompletionsClient(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=secrets.llm_api_key,
            timeout=180.0,
        )
        return chat, GitHubRepository(settings.github_repo, secrets.github_token)

    return build
