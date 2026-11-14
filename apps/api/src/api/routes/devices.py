from __future__ import annotations

from fastapi import APIRouter, status

from api.dependencies import DeviceServiceDep, UserDep
from api.schemas import DeviceCreate, DeviceOut, DeviceStatusOut

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


# TODO: POST /devices/{device_id}/commands — authorise SEND_DEVICE_COMMAND, validate against the
# board's command allowlist, publish via DeviceCommandPublisher (IoT Core), audit-log it.
