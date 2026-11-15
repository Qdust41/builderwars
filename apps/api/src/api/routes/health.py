from __future__ import annotations

from fastapi import APIRouter

from api.dependencies import ContainerDep
from api.schemas import ClientConfigOut, HealthOut
from api.settings import AuthMode

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(container: ContainerDep) -> HealthOut:
    # Liveness only. TODO: separate readiness check once real dependencies (DB) exist.
    return HealthOut(status="ok", environment=container.settings.app_env.value)


@router.get("/client-config", response_model=ClientConfigOut)
def client_config(container: ContainerDep) -> ClientConfigOut:
    """How a command-line client signs in (public, like ``/health``; ids only, no secrets).

    The ``builderwars`` CLI reads this so ``builderwars login`` needs only the API address.
    """
    settings = container.settings
    if settings.auth_mode is AuthMode.COGNITO:
        return ClientConfigOut(
            environment=settings.app_env.value,
            auth_mode="cognito",
            cognito_region=settings.cognito_region,
            cognito_user_pool_id=settings.cognito_user_pool_id,
            cognito_app_client_id=settings.cognito_app_client_id,
        )
    return ClientConfigOut(environment=settings.app_env.value, auth_mode="dev-header")
