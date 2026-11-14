from __future__ import annotations

import pytest
from pydantic import ValidationError

from application.realtime import MAX_EVENT_BYTES, RealtimeEvent, RealtimeEventType


def _event(data: dict) -> RealtimeEvent:
    return RealtimeEvent(
        type=RealtimeEventType.DEVICE_STATUS_CHANGED, project_id="p", session_id="s", data=data
    )


def test_channel_is_scoped_to_project_and_session() -> None:
    assert _event({}).channel == "projects/p/sessions/s"


@pytest.mark.parametrize(
    "data",
    [
        {"private_key": "x"},
        {"nested": {"Token": "x"}},
        {"items": [{"command": "reboot"}]},
    ],
)
def test_events_reject_secret_or_command_fields(data: dict) -> None:
    with pytest.raises(ValidationError):
        _event(data)


def test_events_reject_oversized_data() -> None:
    with pytest.raises(ValidationError, match="limit"):
        _event({"blob": "x" * (MAX_EVENT_BYTES + 1)})


def test_unknown_event_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RealtimeEvent.model_validate({"type": "device.flash", "project_id": "p", "session_id": "s"})
