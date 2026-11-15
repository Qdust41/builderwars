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
    COGNITO = "cognito"  # verifies Cognito JWTs against the user pool JWKS


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
    # AWS only (set by infrastructure/stacks/api.py). DATABASE_SECRET_ARN is the RDS-generated
    # secret, resolved into DATABASE_URL at cold start when DATABASE_URL is not set (ADR 0007).
    database_secret_arn: str | None = None
    jobs_queue_url: str | None = None
    commands_queue_url: str | None = None
    events_http_dns: str | None = None  # AppSync Events HTTP endpoint host
    aws_region: str | None = None  # Lambda sets AWS_REGION
    # Auto-fix (ADR 0012): the run queue. Without it (AWS) auto-fix is off.
    autofix_queue_url: str | None = None
    # LOCAL ONLY: the app-wide model for runs in the API process. In AWS the auto-fix worker
    # gets these from the deploy (GitHub Actions variables + secret) instead.
    autofix_llm_base_url: str | None = None
    autofix_llm_model: str | None = None
    autofix_llm_api_key: SecretStr | None = None

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
        # Without these a deployed API would accept jobs, commands and session events that
        # nothing ever delivers.
        missing = [
            name
            for name, value in (
                ("JOBS_QUEUE_URL", settings.jobs_queue_url),
                ("COMMANDS_QUEUE_URL", settings.commands_queue_url),
                ("EVENTS_HTTP_DNS", settings.events_http_dns),
                ("AWS_REGION", settings.aws_region),
            )
            if not value
        ]
        if missing:
            raise UnsafeConfigurationError(
                f"{', '.join(missing)} must be set when APP_ENV={settings.app_env.value}"
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
    if settings.repository_backend is RepositoryBackend.POSTGRES and settings.database_url is None:
        raise UnsafeConfigurationError("REPOSITORY_BACKEND=postgres needs DATABASE_URL")
    return settings
