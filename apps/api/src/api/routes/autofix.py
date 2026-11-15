"""Auto-fix: link an OpenAI-compatible endpoint + GitHub repository to a project, and see or
start the runs that turn device errors into pull requests (ADR 0012, docs/autofix.md)."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from api.dependencies import AutoFixServiceDep, UserDep
from api.schemas import AutoFixRunCreate, AutoFixRunOut, AutoFixSettingsIn, AutoFixSettingsOut
from application.services import AutoFixSettingsInput
from domain.common import NotFoundError

router = APIRouter(tags=["autofix"])


@router.get("/projects/{project_id}/autofix", response_model=AutoFixSettingsOut)
def get_autofix_settings(
    project_id: str, user: UserDep, service: AutoFixServiceDep
) -> AutoFixSettingsOut:
    settings = service.get_settings(user_id=user.user_id, project_id=project_id)
    if settings is None:
        raise NotFoundError("auto-fix settings", project_id)
    return AutoFixSettingsOut.of(settings)


@router.put("/projects/{project_id}/autofix", response_model=AutoFixSettingsOut)
def save_autofix_settings(
    project_id: str, body: AutoFixSettingsIn, user: UserDep, service: AutoFixServiceDep
) -> AutoFixSettingsOut:
    """Owner/admin. Keys are stored in Secrets Manager and never returned."""
    settings = service.save_settings(
        user_id=user.user_id,
        project_id=project_id,
        data=AutoFixSettingsInput(**body.model_dump()),
    )
    return AutoFixSettingsOut.of(settings)


@router.delete("/projects/{project_id}/autofix", status_code=status.HTTP_204_NO_CONTENT)
def delete_autofix_settings(project_id: str, user: UserDep, service: AutoFixServiceDep) -> Response:
    """Owner/admin. Unlinks the endpoint and repository and deletes the stored keys."""
    service.delete_settings(user_id=user.user_id, project_id=project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/autofix/runs",
    response_model=AutoFixRunOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_autofix(
    project_id: str, body: AutoFixRunCreate, user: UserDep, service: AutoFixServiceDep
) -> AutoFixRunOut:
    """Members and up. Counts toward the daily cap; ignores the dedupe window."""
    run = service.request_fix(
        user_id=user.user_id,
        project_id=project_id,
        device_id=body.device_id,
        message=body.message,
        level=body.level,
    )
    return AutoFixRunOut.of(run)


@router.get("/projects/{project_id}/autofix/runs", response_model=list[AutoFixRunOut])
def list_autofix_runs(
    project_id: str, user: UserDep, service: AutoFixServiceDep
) -> list[AutoFixRunOut]:
    """The 50 most recent runs, newest first."""
    return [
        AutoFixRunOut.of(r) for r in service.list_runs(user_id=user.user_id, project_id=project_id)
    ]


@router.get("/projects/{project_id}/autofix/runs/{run_id}", response_model=AutoFixRunOut)
def get_autofix_run(
    project_id: str, run_id: str, user: UserDep, service: AutoFixServiceDep
) -> AutoFixRunOut:
    return AutoFixRunOut.of(
        service.get_run(user_id=user.user_id, project_id=project_id, run_id=run_id)
    )
