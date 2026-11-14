from __future__ import annotations

from fastapi import APIRouter, status

from api.dependencies import SessionServiceDep, UserDep
from api.schemas import SessionCreate, SessionOut

router = APIRouter(tags=["sessions"])


@router.get("/projects/{project_id}/sessions", response_model=list[SessionOut])
def list_sessions(project_id: str, user: UserDep, service: SessionServiceDep) -> list[SessionOut]:
    return [
        SessionOut.of(s) for s in service.list_sessions(user_id=user.user_id, project_id=project_id)
    ]


@router.post(
    "/projects/{project_id}/sessions",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
)
def start_session(
    project_id: str, body: SessionCreate, user: UserDep, service: SessionServiceDep
) -> SessionOut:
    session = service.start_session(
        user_id=user.user_id, project_id=project_id, device_id=body.device_id
    )
    return SessionOut.of(session)


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: str, user: UserDep, service: SessionServiceDep) -> SessionOut:
    return SessionOut.of(service.get_session(user_id=user.user_id, session_id=session_id))
