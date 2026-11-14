from __future__ import annotations

from application.ports import DeviceRepository, RealtimePublisher, SessionRepository
from application.realtime import RealtimeEvent, RealtimeEventType
from application.services.authorization import Authorizer
from domain.common import NotFoundError
from domain.projects import Permission
from domain.sessions import Session


class SessionService:
    def __init__(
        self,
        sessions: SessionRepository,
        devices: DeviceRepository,
        authorizer: Authorizer,
        realtime: RealtimePublisher,
    ) -> None:
        self._sessions = sessions
        self._devices = devices
        self._authorizer = authorizer
        self._realtime = realtime

    def start_session(
        self, *, user_id: str, project_id: str, device_id: str | None = None
    ) -> Session:
        self._authorizer.require(user_id, project_id, Permission.START_SESSION)
        if device_id is not None:
            device = self._devices.get(device_id)
            if device is None or device.project_id != project_id:
                raise NotFoundError("device", device_id)
        session = Session(project_id=project_id, created_by=user_id, device_id=device_id)
        self._sessions.add(session)
        self._realtime.publish(
            RealtimeEvent(
                type=RealtimeEventType.PROJECT_ACTIVITY,
                project_id=project_id,
                session_id=session.id,
                actor_id=user_id,
                data={"activity": "session.started"},
            )
        )
        return session

    def list_sessions(self, *, user_id: str, project_id: str) -> list[Session]:
        self._authorizer.require(user_id, project_id, Permission.VIEW_PROJECT)
        return self._sessions.list_for_project(project_id)

    def get_session(self, *, user_id: str, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise NotFoundError("session", session_id)
        try:
            self._authorizer.require(user_id, session.project_id, Permission.JOIN_SESSION)
        except NotFoundError:
            raise NotFoundError("session", session_id) from None
        return session
