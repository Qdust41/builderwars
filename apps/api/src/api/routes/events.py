"""Realtime subscription info.

Clients subscribe to AppSync Events directly, but only after the API confirms membership and
tells them which channel to use. TODO: issue short-lived subscription authorisation (or rely on
an AppSync onSubscribe handler that checks membership) — see docs/architecture.md.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.dependencies import SessionServiceDep, UserDep
from api.schemas import SessionChannelOut
from application.realtime import DEVICE_EVENT_TYPES, RealtimeEventType, session_channel

router = APIRouter(tags=["realtime"])


@router.get("/sessions/{session_id}/channel", response_model=SessionChannelOut)
def get_session_channel(
    session_id: str, user: UserDep, service: SessionServiceDep
) -> SessionChannelOut:
    session = service.get_session(user_id=user.user_id, session_id=session_id)
    return SessionChannelOut(
        session_id=session.id,
        channel=session_channel(session.project_id, session.id),
        event_types=[t for t in RealtimeEventType if t not in DEVICE_EVENT_TYPES],
    )
