from __future__ import annotations

from datetime import datetime

from application.ports import DeviceIdentityProvisioner, DeviceRepository
from application.services.authorization import Authorizer
from domain.common import NotFoundError, utcnow
from domain.devices import Device
from domain.projects import Permission


class DeviceService:
    """Device registry operations.

    A device is one host PC + FREE-WILi pair, and one AWS IoT thing whose name is the device id
    (spec 03). Revoking marks the record first, so ingest quarantines the device's messages even
    if the IoT call fails, and then revokes its certificates in IoT Core.
    """

    def __init__(
        self,
        devices: DeviceRepository,
        authorizer: Authorizer,
        provisioner: DeviceIdentityProvisioner,
    ) -> None:
        self._devices = devices
        self._authorizer = authorizer
        self._provisioner = provisioner

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
        # TODO (spec 03): create the IoT thing + certificate through the provisioner, once the
        # certificate approach (CSR from the host, or AWS-generated key) is decided.
        return device

    def revoke_device(self, *, user_id: str, device_id: str, now: datetime | None = None) -> Device:
        """Revoke a device. Idempotent: repeating it re-runs the IoT revocation and succeeds."""
        device = self._load_for(user_id, device_id, Permission.REVOKE_DEVICE)
        revoked = device.revoke(now or utcnow())
        if revoked is not device:
            self._devices.save(revoked)
        self._provisioner.revoke(device.id)
        # TODO (spec 03, open question): cancel the device's pending commands on revoke.
        return revoked

    def list_devices(self, *, user_id: str, project_id: str) -> list[Device]:
        self._authorizer.require(user_id, project_id, Permission.VIEW_PROJECT)
        return self._devices.list_for_project(project_id)

    def get_device(self, *, user_id: str, device_id: str) -> Device:
        return self._load_for(user_id, device_id, Permission.VIEW_PROJECT)

    def _load_for(self, user_id: str, device_id: str, permission: Permission) -> Device:
        device = self._devices.get(device_id)
        if device is None:
            raise NotFoundError("device", device_id)
        try:
            self._authorizer.require(user_id, device.project_id, permission)
        except NotFoundError:
            raise NotFoundError("device", device_id) from None
        return device
