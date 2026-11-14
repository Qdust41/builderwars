from __future__ import annotations

from typing import Protocol


class DeviceIdentityProvisioner(Protocol):
    """Manages a device's AWS IoT identity: its thing, X.509 certificate and policy (spec 03).

    The thing name is the device id, so the IoT policy's ``${iot:Connection.Thing.ThingName}``
    pins each device to its own client id and topics. Implementations never persist or log
    private keys.
    """

    def revoke(self, thing_name: str) -> None:
        """Stop the device connecting: revoke every certificate attached to the thing.

        Must be idempotent (a retried revoke succeeds) and must succeed when the thing does
        not exist (the device was registered but never provisioned).
        """
        ...
