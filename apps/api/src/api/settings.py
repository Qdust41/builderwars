from __future__ import annotations

from enum import StrEnum

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    LOCAL = "local"
    TEST = "test"
    DEV = "dev"
    PROD = "prod"


class AuthMode(StrEnum):
    DEV_HEADER = "dev-header"  # trusts an X-Dev-User header. LOCAL/TEST ONLY.
    COGNITO = "cognito"  # verifies Cognito JWTs against the user pool JWKS


class RepositoryBackend(StrEnum):
    MEMORY = "memory"  # in-process fakes. LOCAL/TEST ONLY.
    POSTGRES = "postgres"  # TODO: not implemented yet


LOCAL_ONLY_ENVS = frozenset({AppEnv.LOCAL, AppEnv.TEST})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    app_env: AppEnv = AppEnv.LOCAL
    auth_mode: AuthMode = AuthMode.DEV_HEADER
    repository_backend: RepositoryBackend = RepositoryBackend.MEMORY
    cors_allow_origins: list[str] = ["http://localhost:5173"]

    # AUTH_MODE=cognito. Ids, not secrets: the stack passes them as Lambda environment.
    cognito_region: str = "us-east-1"
    cognito_user_pool_id: str | None = None
    cognito_app_client_id: str | None = None
    # Override for tests or a local JWKS; defaults to the user pool's well-known URL.
    cognito_jwks_url: str | None = None

    @property
    def cognito_issuer(self) -> str:
        return (
            f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_user_pool_id}"
        )

    @property
    def cognito_jwks_endpoint(self) -> str:
        return self.cognito_jwks_url or f"{self.cognito_issuer}/.well-known/jwks.json"


class UnsafeConfigurationError(RuntimeError):
    pass


class MissingConfigurationError(RuntimeError):
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
    if settings.auth_mode is AuthMode.COGNITO:
        missing = [
            name
            for name in ("cognito_user_pool_id", "cognito_app_client_id")
            if not getattr(settings, name)
        ]
        if missing:
            raise MissingConfigurationError(
                "AUTH_MODE=cognito needs " + ", ".join(n.upper() for n in missing)
            )
    return settings
