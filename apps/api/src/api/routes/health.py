from __future__ import annotations

from fastapi import APIRouter

from api.dependencies import ContainerDep
from api.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(container: ContainerDep) -> HealthOut:
    # Liveness only. TODO: separate readiness check once real dependencies (DB) exist.
    return HealthOut(status="ok", environment=container.settings.app_env.value)
