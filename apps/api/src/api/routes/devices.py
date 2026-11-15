from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, HTTPException, Query, status

from api.dependencies import (
    CommandServiceDep,
    DeviceServiceDep,
    DeviceUploadServiceDep,
    TelemetryServiceDep,
    UserDep,
)
from api.schemas import (
    CommandCreate,
    CommandOut,
    DeviceChannelOut,
    DeviceCreate,
    DeviceLogEntryOut,
    DeviceLogHistoryOut,
    DeviceLogRecordOut,
    DeviceMessageResultOut,
    DeviceMessagesUpload,
    DeviceMessagesUploadOut,
    DeviceOut,
    DeviceStatusOut,
    TelemetrySampleOut,
    TelemetryValue,
)
from application.realtime import DEVICE_EVENT_TYPES, device_channel
from application.services import IngestOutcome, UploadedMessage
from application.services.telemetry import (
    MAX_LOG_ENTRIES,
    MAX_LOG_HISTORY_PAGE,
    MAX_TELEMETRY_SAMPLES,
    InvalidLogCursorError,
)

router = APIRouter(tags=["devices"])


@router.get("/projects/{project_id}/devices", response_model=list[DeviceOut])
def list_devices(project_id: str, user: UserDep, service: DeviceServiceDep) -> list[DeviceOut]:
    return [
        DeviceOut.of(d) for d in service.list_devices(user_id=user.user_id, project_id=project_id)
    ]


@router.post(
    "/projects/{project_id}/devices",
    response_model=DeviceOut,
    status_code=status.HTTP_201_CREATED,
)
def register_device(
    project_id: str, body: DeviceCreate, user: UserDep, service: DeviceServiceDep
) -> DeviceOut:
    """Create the device record. Does NOT provision IoT credentials (not implemented)."""
    device = service.register_device(
        user_id=user.user_id,
        project_id=project_id,
        display_name=body.display_name,
        hardware_model=body.hardware_model,
        extensions=frozenset(body.extensions),
    )
    return DeviceOut.of(device)


@router.get("/devices/{device_id}", response_model=DeviceOut)
def get_device(device_id: str, user: UserDep, service: DeviceServiceDep) -> DeviceOut:
    return DeviceOut.of(service.get_device(user_id=user.user_id, device_id=device_id))


@router.get("/devices/{device_id}/status", response_model=DeviceStatusOut)
def get_device_status(device_id: str, user: UserDep, service: DeviceServiceDep) -> DeviceStatusOut:
    device = service.get_device(user_id=user.user_id, device_id=device_id)
    return DeviceStatusOut(
        device_id=device.id,
        connection_status=device.connection_status,
        firmware_version=device.firmware_version,
        last_seen_at=device.last_seen_at,
    )


@router.post(
    "/projects/{project_id}/devices/{device_id}/commands",
    response_model=CommandOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def send_command(
    project_id: str,
    device_id: str,
    body: CommandCreate,
    user: UserDep,
    service: CommandServiceDep,
) -> CommandOut:
    """Queue a command for the device (role-based, no lock; FIFO per device, max 32 pending).

    The dispatcher worker publishes it; the result arrives asynchronously. Poll
    ``GET /commands/{id}`` (session broadcast of results: TODO).
    """
    command = service.request_command(
        user_id=user.user_id,
        project_id=project_id,
        device_id=device_id,
        name=body.name,
        args=body.args,
    )
    return CommandOut.of(command)


@router.get("/commands/{command_id}", response_model=CommandOut)
def get_command(command_id: str, user: UserDep, service: CommandServiceDep) -> CommandOut:
    return CommandOut.of(service.get_command(user_id=user.user_id, command_id=command_id))


@router.get("/devices/{device_id}/telemetry", response_model=list[TelemetrySampleOut])
def get_device_telemetry(
    device_id: str,
    user: UserDep,
    service: TelemetryServiceDep,
    limit: Annotated[int, Query(ge=1, le=MAX_TELEMETRY_SAMPLES)] = 300,
) -> list[TelemetrySampleOut]:
    """The newest ``limit`` telemetry samples, oldest first."""
    samples = service.recent_telemetry(user_id=user.user_id, device_id=device_id, limit=limit)
    return [
        TelemetrySampleOut(ts=s.at, readings=cast(dict[str, TelemetryValue], s.readings))
        for s in samples
    ]


@router.get("/devices/{device_id}/logs", response_model=list[DeviceLogEntryOut])
def get_device_logs(
    device_id: str,
    user: UserDep,
    service: TelemetryServiceDep,
    limit: Annotated[int, Query(ge=1, le=MAX_LOG_ENTRIES)] = 200,
) -> list[DeviceLogEntryOut]:
    """The newest ``limit`` log lines and device events, oldest first."""
    entries = service.recent_logs(user_id=user.user_id, device_id=device_id, limit=limit)
    return [
        DeviceLogEntryOut(
            at=e.at, kind=cast(Literal["log", "event"], e.kind), level=e.level, message=e.message
        )
        for e in entries
    ]


@router.get("/devices/{device_id}/logs/history", response_model=DeviceLogHistoryOut)
def get_device_log_history(
    device_id: str,
    user: UserDep,
    service: TelemetryServiceDep,
    since: Annotated[datetime | None, Query(description="only entries at or after this")] = None,
    until: Annotated[datetime | None, Query(description="only entries before this")] = None,
    cursor: Annotated[str | None, Query(description="next_cursor from the previous page")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LOG_HISTORY_PAGE)] = MAX_LOG_HISTORY_PAGE,
) -> DeviceLogHistoryOut:
    """A device's full log and event history, oldest first, paged with ``next_cursor``.

    Used by ``builderwars logs export``; any project member can read it. Timestamps without
    a timezone are taken as UTC.
    """
    try:
        page = service.log_history(
            user_id=user.user_id,
            device_id=device_id,
            since=since,
            until=until,
            cursor=cursor,
            limit=limit,
        )
    except InvalidLogCursorError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return DeviceLogHistoryOut(
        entries=[
            DeviceLogRecordOut(
                at=e.at,
                kind=cast(Literal["log", "event"], e.kind),
                level=e.level,
                message=e.message,
                message_id=e.message_id,
            )
            for e in page.entries
        ],
        next_cursor=page.next_cursor,
    )


@router.get("/devices/{device_id}/channel", response_model=DeviceChannelOut)
def get_device_channel(
    device_id: str, user: UserDep, service: DeviceServiceDep
) -> DeviceChannelOut:
    """Realtime channel for this device's telemetry, logs and command updates (members only)."""
    device = service.get_device(user_id=user.user_id, device_id=device_id)
    return DeviceChannelOut(
        device_id=device.id,
        channel=device_channel(device.project_id, device.id),
        event_types=list(DEVICE_EVENT_TYPES),
    )


@router.post("/devices/{device_id}/messages", response_model=DeviceMessagesUploadOut)
def upload_device_messages(
    device_id: str,
    body: DeviceMessagesUpload,
    user: UserDep,
    service: DeviceUploadServiceDep,
) -> DeviceMessagesUploadOut:
    """Record a board's messages uploaded by a signed-in member (the ``builderwars`` CLI).

    Each message is ``{topic, payload}`` exactly as the board would publish it over MQTT, and
    must name this device. Messages go through the same validation and de-duplication as the
    MQTT path, so uploading the same messages again is harmless, and viewers of the device get
    its telemetry and logs live. One rejected message does not fail the others: check
    ``results`` (same order as ``messages``).
    """
    results = service.upload(
        user_id=user.user_id,
        device_id=device_id,
        messages=[
            UploadedMessage(topic=m.topic, body=json.dumps(m.payload).encode())
            for m in body.messages
        ],
        received_at=datetime.now(UTC),
    )
    out = [
        DeviceMessageResultOut(
            outcome=r.outcome,
            message_id=r.message_id,
            reason=r.reason.value if r.reason else None,
            detail=r.detail,
        )
        for r in results
    ]
    return DeviceMessagesUploadOut(
        processed=sum(r.outcome is IngestOutcome.PROCESSED for r in results),
        duplicate=sum(r.outcome is IngestOutcome.DUPLICATE for r in results),
        rejected=sum(r.outcome is IngestOutcome.REJECTED for r in results),
        results=out,
    )
