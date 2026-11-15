"""LOCAL ONLY: the bridge between a simulated host, this API process and the browser.

In AWS a host publishes over MQTT to IoT Core, the ingest worker records the message, the
dispatcher publishes commands back over IoT Core, and AppSync Events notifies browsers. Locally
everything is in one process, so these routes stand in for those hops:

* ``POST /local/device-messages`` — a host message, as the IoT rule would forward it.
* ``POST /local/devices/{device_id}/commands/next`` — the host collects its queued commands.
* ``GET /local/realtime?channel=...`` — server-sent events in place of AppSync Events.

They are mounted only when ``APP_ENV`` is ``local`` or ``test`` (``container.local``), with
either repository backend. They are left out of the
OpenAPI contract on purpose. The host routes take no credentials, like a broker on localhost.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.dependencies import ContainerDep, LocalDevBridge, UserDep
from application.adapters import memory
from application.realtime import resource_id_from_segment
from application.services import CommandDispatchService
from device_protocol import encode_message, topic_for_message
from domain.common import NotFoundError
from domain.projects import Permission

router = APIRouter(prefix="/local", tags=["local-dev"], include_in_schema=False)

KEEPALIVE_S = 15.0
_CHANNEL = re.compile(
    r"^projects/(?P<project>[A-Za-z0-9-]{1,50})/(?P<kind>sessions|devices)/(?P<id>[A-Za-z0-9-]{1,50})$"
)


class DeviceMessageIn(BaseModel):
    topic: str = Field(max_length=256)
    payload: dict[str, Any]


class DeviceMessageResult(BaseModel):
    outcome: str
    reason: str | None = None
    detail: str | None = None


class OutgoingDeviceMessage(BaseModel):
    topic: str
    payload: dict[str, Any]


def _bridge(container: ContainerDep) -> LocalDevBridge:
    if container.local is None:  # pragma: no cover - router is not mounted then
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return container.local


@router.post("/device-messages", response_model=DeviceMessageResult)
def post_device_message(body: DeviceMessageIn, container: ContainerDep) -> DeviceMessageResult:
    result = _bridge(container).ingest.ingest(
        topic=body.topic,
        body=json.dumps(body.payload).encode(),
        received_at=datetime.now(UTC),
    )
    return DeviceMessageResult(
        outcome=result.outcome.value,
        reason=result.reason.value if result.reason else None,
        detail=result.detail,
    )


@router.post("/devices/{device_id}/commands/next", response_model=list[OutgoingDeviceMessage])
def take_device_commands(device_id: str, container: ContainerDep) -> list[OutgoingDeviceMessage]:
    bridge = _bridge(container)

    def for_device(command_id: str) -> bool:
        command = bridge.commands.get(command_id)
        return command is not None and command.device_id == device_id

    publisher = memory.RecordingCommandPublisher()
    dispatcher = CommandDispatchService(bridge.commands, publisher, bridge.events)
    for command_id in bridge.command_queue.take(for_device):
        dispatcher.dispatch(command_id)
    return [
        OutgoingDeviceMessage(
            topic=topic_for_message(env.device_id, env.message_type),
            payload=json.loads(encode_message(env)),
        )
        for env in publisher.commands
    ]


@router.get("/realtime")
async def stream_realtime(
    request: Request,
    container: ContainerDep,
    user: UserDep,
    channel: Annotated[str, Query(max_length=256)],
) -> StreamingResponse:
    """Server-sent events for one channel, after the same membership check as the API."""
    bridge = _bridge(container)
    match = _CHANNEL.match(channel)
    if match is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown channel")
    project_id = resource_id_from_segment(match["project"])
    resource_id = resource_id_from_segment(match["id"])
    container.authorizer.require(user.user_id, project_id, Permission.VIEW_PROJECT)
    if match["kind"] == "devices":
        device = container.devices.get_device(user_id=user.user_id, device_id=resource_id)
        found = device.project_id
    else:
        session = container.sessions.get_session(user_id=user.user_id, session_id=resource_id)
        found = session.project_id
    if found != project_id:
        raise NotFoundError(match["kind"][:-1], resource_id)

    async def events() -> AsyncIterator[str]:
        with bridge.realtime.subscribe(channel) as queue:
            yield ": subscribed\n\n"
            while not await request.is_disconnected():
                try:
                    data = await asyncio.wait_for(queue.get(), KEEPALIVE_S)
                except TimeoutError:
                    yield ": keepalive\n\n"
                else:
                    yield f"data: {data}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
