from __future__ import annotations

from application.ports import DeviceRepository
from application.services.authorization import Authorizer
from domain.common import NotFoundError
from domain.devices import Device
from domain.projects import Permission


class DeviceService:
    """Device registry operations.

    A device is one host PC + FREE-WILi pair. Registering creates the application record
    only. Provisioning the AWS IoT thing/certificate is a separate, privileged flow
    (spec 03, docs/security.md) and is not implemented.
    """

    def __init__(self, devices: DeviceRepository, authorizer: Authorizer) -> None:
        self._devices = devices
        self._authorizer = authorizer

    def register_device(
        self,
        *,
        user_id: str,
        project_id: str,
        display_name: str,
        hardware_model: str,
        extensions: frozenset[str] = frozenset(),
    ) -> Device:
        self._authorizer.require(user_id, project_id, Permission.REGISTER_DEVICE)
        device = Device(
            project_id=project_id,
            display_name=display_name,
            hardware_model=hardware_model,
            extensions=extensions,
        )
        self._devices.add(device)
        # TODO: request IoT thing provisioning via a dedicated port + job.
        return device

    def list_devices(self, *, user_id: str, project_id: str) -> list[Device]:
        self._authorizer.require(user_id, project_id, Permission.VIEW_PROJECT)
        return self._devices.list_for_project(project_id)

    def get_device(self, *, user_id: str, device_id: str) -> Device:
        device = self._devices.get(device_id)
        if device is None:
            raise NotFoundError("device", device_id)
        try:
            self._authorizer.require(user_id, device.project_id, Permission.VIEW_PROJECT)
        except NotFoundError:
            raise NotFoundError("device", device_id) from None
        return device
