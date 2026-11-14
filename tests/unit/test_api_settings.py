from __future__ import annotations

import pytest

from api.settings import (
    AppEnv,
    AuthMode,
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


def test_postgres_backend_needs_a_database_url() -> None:
    with pytest.raises(UnsafeConfigurationError, match="DATABASE_URL"):
        validate_settings(
            Settings(
                app_env=AppEnv.LOCAL,
                repository_backend=RepositoryBackend.POSTGRES,
                database_url=None,
            )
        )


def test_worker_settings_refuse_memory_outside_local_and_postgres_without_url() -> None:
    from workers.settings import (
        RepositoryBackend as WorkerBackend,
    )
    from workers.settings import (
        UnsafeConfigurationError as WorkerConfigError,
    )
    from workers.settings import (
        WorkerSettings,
        validate_worker_settings,
    )

    with pytest.raises(WorkerConfigError, match="memory"):
        validate_worker_settings(
            WorkerSettings(app_env="prod", repository_backend=WorkerBackend.MEMORY)
        )
    with pytest.raises(WorkerConfigError, match="DATABASE_URL"):
        validate_worker_settings(
            WorkerSettings(repository_backend=WorkerBackend.POSTGRES, database_url=None)
        )
