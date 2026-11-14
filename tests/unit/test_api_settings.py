from __future__ import annotations

import pytest

from api.settings import (
    AppEnv,
    AuthMode,
    MissingConfigurationError,
    RepositoryBackend,
    Settings,
    UnsafeConfigurationError,
    validate_settings,
)


@pytest.mark.parametrize("env", [AppEnv.DEV, AppEnv.PROD])
def test_dev_header_auth_is_refused_outside_local(env: AppEnv) -> None:
    with pytest.raises(UnsafeConfigurationError, match="AUTH_MODE"):
        validate_settings(Settings(app_env=env, auth_mode=AuthMode.DEV_HEADER))


@pytest.mark.parametrize("env", [AppEnv.DEV, AppEnv.PROD])
def test_memory_repositories_are_refused_outside_local(env: AppEnv) -> None:
    with pytest.raises(UnsafeConfigurationError, match="REPOSITORY_BACKEND"):
        validate_settings(
            Settings(
                app_env=env, auth_mode=AuthMode.COGNITO, repository_backend=RepositoryBackend.MEMORY
            )
        )


def test_local_defaults_are_accepted() -> None:
    assert validate_settings(Settings(app_env=AppEnv.LOCAL)).app_env is AppEnv.LOCAL


def test_cognito_mode_requires_pool_and_client_ids() -> None:
    with pytest.raises(MissingConfigurationError, match="COGNITO_USER_POOL_ID"):
        validate_settings(Settings(app_env=AppEnv.TEST, auth_mode=AuthMode.COGNITO))
    settings = Settings(
        app_env=AppEnv.TEST,
        auth_mode=AuthMode.COGNITO,
        cognito_user_pool_id="us-east-1_abc",
        cognito_app_client_id="client",
    )
    assert validate_settings(settings).cognito_jwks_endpoint == (
        "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_abc/.well-known/jwks.json"
    )
