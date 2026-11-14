from __future__ import annotations

from enum import StrEnum

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    LOCAL = "local"
    TEST = "test"
    DEV = "dev"
    PROD = "prod"


class AuthMode(StrEnum):
    DEV_HEADER = "dev-header"  # trusts an X-Dev-User header. LOCAL/TEST ONLY.
    COGNITO = "cognito"  # TODO: verify Cognito JWTs


class RepositoryBackend(StrEnum):
    MEMORY = "memory"  # in-process fakes. LOCAL/TEST ONLY.
    POSTGRES = "postgres"  # needs DATABASE_URL and a migrated schema


LOCAL_ONLY_ENVS = frozenset({AppEnv.LOCAL, AppEnv.TEST})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    app_env: AppEnv = AppEnv.LOCAL
    auth_mode: AuthMode = AuthMode.DEV_HEADER
    repository_backend: RepositoryBackend = RepositoryBackend.MEMORY
    cors_allow_origins: list[str] = ["http://localhost:5173"]
    # postgresql://user:password@host:5432/db. Required when REPOSITORY_BACKEND=postgres.
    database_url: SecretStr | None = None
    database_pool_max_size: int = 5


class UnsafeConfigurationError(RuntimeError):
    pass


def validate_settings(settings: Settings) -> Settings:
    """Refuse to run local-only shortcuts outside local/test environments."""
    if settings.app_env not in LOCAL_ONLY_ENVS:
        if settings.auth_mode is AuthMode.DEV_HEADER:
            raise UnsafeConfigurationError(
                f"AUTH_MODE=dev-header is not allowed when APP_ENV={settings.app_env.value}"
            )
        if settings.repository_backend is RepositoryBackend.MEMORY:
            raise UnsafeConfigurationError(
                f"REPOSITORY_BACKEND=memory is not allowed when APP_ENV={settings.app_env.value}"
            )
    if settings.repository_backend is RepositoryBackend.POSTGRES and settings.database_url is None:
        raise UnsafeConfigurationError("REPOSITORY_BACKEND=postgres needs DATABASE_URL")
    return settings
