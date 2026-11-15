"""Worker configuration, read from the environment (same variable names as the API)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class RepositoryBackend(StrEnum):
    MEMORY = "memory"  # in-process fakes. LOCAL/TEST ONLY.
    POSTGRES = "postgres"


LOCAL_ONLY_ENVS = frozenset({"local", "test"})


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    app_env: str = "local"
    repository_backend: RepositoryBackend = RepositoryBackend.MEMORY
    database_url: SecretStr | None = None
    database_pool_max_size: int = 1  # one message at a time per process / Lambda container


class UnsafeConfigurationError(RuntimeError):
    pass


def validate_worker_settings(settings: WorkerSettings) -> WorkerSettings:
    if (
        settings.repository_backend is RepositoryBackend.MEMORY
        and settings.app_env not in LOCAL_ONLY_ENVS
    ):
        raise UnsafeConfigurationError(
            f"REPOSITORY_BACKEND=memory is not allowed when APP_ENV={settings.app_env}"
        )
    if settings.repository_backend is RepositoryBackend.POSTGRES and settings.database_url is None:
        raise UnsafeConfigurationError("REPOSITORY_BACKEND=postgres needs DATABASE_URL")
    return settings
