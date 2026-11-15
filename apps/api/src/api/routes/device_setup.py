"""The test setup behind a device (laptop -> FREE-WILi -> up to 4 target boards) and the
target boards' sensors. People edit boards and sensors in the web app (``device:configure``,
the project owner for now); the ``builderwars`` CLI reports the laptop and FREE-WILi, then
downloads the sensors and reads them through the FREE-WILi."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from api.dependencies import DeviceSetupServiceDep, UserDep
from api.schemas import DeviceSetupOut, SensorIn, SensorOut, TargetBoardIn, TargetBoardOut
from device_protocol.sensor_presets import SENSOR_PRESETS, SensorPreset
from device_protocol.sensors import SensorSpec
from device_protocol.setup import SetupReport

router = APIRouter(tags=["device setup"])


def _spec(body: SensorIn) -> SensorSpec:
    return SensorSpec.model_validate(body.model_dump(exclude={"board_id"}))


@router.get("/devices/{device_id}/setup", response_model=DeviceSetupOut)
def get_device_setup(
    device_id: str, user: UserDep, service: DeviceSetupServiceDep
) -> DeviceSetupOut:
    """Laptop, FREE-WILi, target boards and sensors, for the device page (any member)."""
    return DeviceSetupOut.of(service.get_setup(user_id=user.user_id, device_id=device_id))


@router.put("/devices/{device_id}/setup/connection", response_model=DeviceSetupOut)
def report_device_connection(
    device_id: str, body: SetupReport, user: UserDep, service: DeviceSetupServiceDep
) -> DeviceSetupOut:
    """Sent by ``builderwars run`` when it starts: which laptop it runs on and which
    FREE-WILi is plugged in (``device:upload``, so any member running the CLI)."""
    service.report_connection(user_id=user.user_id, device_id=device_id, report=body)
    return DeviceSetupOut.of(service.get_setup(user_id=user.user_id, device_id=device_id))


# -- target boards ------------------------------------------------------------------------------
@router.post(
    "/devices/{device_id}/boards",
    response_model=TargetBoardOut,
    status_code=status.HTTP_201_CREATED,
)
def add_target_board(
    device_id: str, body: TargetBoardIn, user: UserDep, service: DeviceSetupServiceDep
) -> TargetBoardOut:
    """Add a board under test wired to this device's FREE-WILi (at most 4: 409 after)."""
    board = service.add_board(
        user_id=user.user_id, device_id=device_id, name=body.name, notes=body.notes
    )
    return TargetBoardOut.of(board)


@router.put("/devices/{device_id}/boards/{board_id}", response_model=TargetBoardOut)
def update_target_board(
    device_id: str,
    board_id: str,
    body: TargetBoardIn,
    user: UserDep,
    service: DeviceSetupServiceDep,
) -> TargetBoardOut:
    board = service.update_board(
        user_id=user.user_id,
        device_id=device_id,
        board_id=board_id,
        name=body.name,
        notes=body.notes,
    )
    return TargetBoardOut.of(board)


@router.delete(
    "/devices/{device_id}/boards/{board_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_target_board(
    device_id: str, board_id: str, user: UserDep, service: DeviceSetupServiceDep
) -> Response:
    """Remove a board and all of its sensors."""
    service.delete_board(user_id=user.user_id, device_id=device_id, board_id=board_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sensor-presets", response_model=list[SensorPreset])
def list_sensor_presets(user: UserDep) -> list[SensorPreset]:
    """Common sensor parts (TMP102, INA219, ADS1115, MPU-6050, ...) with datasheet settings,
    for the "add sensor" form to start from."""
    return list(SENSOR_PRESETS)


# -- sensors ------------------------------------------------------------------------------------
@router.get("/devices/{device_id}/sensors", response_model=list[SensorOut])
def list_sensors(device_id: str, user: UserDep, service: DeviceSetupServiceDep) -> list[SensorOut]:
    """Every board's sensors, oldest first. ``builderwars run`` reads the enabled ones."""
    return [
        SensorOut.of(s) for s in service.list_sensors(user_id=user.user_id, device_id=device_id)
    ]


@router.post(
    "/devices/{device_id}/sensors", response_model=SensorOut, status_code=status.HTTP_201_CREATED
)
def add_sensor(
    device_id: str, body: SensorIn, user: UserDep, service: DeviceSetupServiceDep
) -> SensorOut:
    """Define a sensor on one of the device's boards. ``key`` must be unique on the device
    across all its boards (409)."""
    sensor = service.add_sensor(
        user_id=user.user_id, device_id=device_id, board_id=body.board_id, spec=_spec(body)
    )
    return SensorOut.of(sensor)


@router.put("/devices/{device_id}/sensors/{sensor_id}", response_model=SensorOut)
def update_sensor(
    device_id: str, sensor_id: str, body: SensorIn, user: UserDep, service: DeviceSetupServiceDep
) -> SensorOut:
    """Replace a sensor's definition (it may move to another of the device's boards)."""
    sensor = service.update_sensor(
        user_id=user.user_id,
        device_id=device_id,
        sensor_id=sensor_id,
        board_id=body.board_id,
        spec=_spec(body),
    )
    return SensorOut.of(sensor)


@router.delete(
    "/devices/{device_id}/sensors/{sensor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_sensor(
    device_id: str, sensor_id: str, user: UserDep, service: DeviceSetupServiceDep
) -> Response:
    service.delete_sensor(user_id=user.user_id, device_id=device_id, sensor_id=sensor_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
