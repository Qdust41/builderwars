from __future__ import annotations

from fastapi import APIRouter, status

from api.dependencies import CommandServiceDep, DeviceServiceDep, UserDep
from api.schemas import CommandCreate, CommandOut, DeviceCreate, DeviceOut, DeviceStatusOut

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
