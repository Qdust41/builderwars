"""Auto-fix: LLM-proposed pull requests for device errors (ADR 0012)."""

from ai_platform.autofix.agent import (
    AnswerError,
    AutoFixWorker,
    ChatModel,
    ClientFactory,
    CodeHost,
    Limits,
    parse_json_answer,
)
from ai_platform.autofix.clients import default_clients
from ai_platform.autofix.github import GitHubRepository, PullRequest, RepoFile

__all__ = [
    "AnswerError",
    "AutoFixWorker",
    "ChatModel",
    "ClientFactory",
    "CodeHost",
    "GitHubRepository",
    "Limits",
    "PullRequest",
    "RepoFile",
    "default_clients",
    "parse_json_answer",
]
