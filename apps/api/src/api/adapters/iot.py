"""AWS IoT Core adapter for ``DeviceIdentityProvisioner`` (spec 03).

The thing name is the device id. Revoking a device revokes every certificate attached to its
thing and detaches it, so the connection fails both the certificate check and the policy's
``iot:Connection.Thing.IsAttached`` condition. Certificates and things are kept (not deleted)
as an audit trail. No key material is ever read, stored or logged here.

The boto3 client is injected, so this module imports no AWS SDK and tests pass a mock.
IAM for the API role (workstream C): ``iot:ListThingPrincipals``, ``iot:UpdateCertificate``,
``iot:DetachThingPrincipal``.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Protocol

log = logging.getLogger(__name__)

REVOKED = "REVOKED"
_NOT_FOUND = "ResourceNotFoundException"


class IotClient(Protocol):
    """The subset of the boto3 ``iot`` client this adapter calls."""

    def list_thing_principals(self, **kwargs: Any) -> dict[str, Any]: ...
    def update_certificate(self, **kwargs: Any) -> dict[str, Any]: ...
    def detach_thing_principal(self, **kwargs: Any) -> dict[str, Any]: ...


class IotDeviceIdentityProvisioner:
    def __init__(self, client: IotClient) -> None:
        self._client = client

    @classmethod
    def from_boto3(cls, region_name: str) -> IotDeviceIdentityProvisioner:
        boto3 = importlib.import_module("boto3")
        return cls(boto3.client("iot", region_name=region_name))

    def revoke(self, thing_name: str) -> None:
        for principal in self._thing_principals(thing_name):
            certificate_id = certificate_id_from_arn(principal)
            if certificate_id is None:
                continue
            try:
                self._client.update_certificate(certificateId=certificate_id, newStatus=REVOKED)
                self._client.detach_thing_principal(thingName=thing_name, principal=principal)
            except Exception as exc:
                if _error_code(exc) != _NOT_FOUND:
                    raise
                # Already gone (a concurrent or earlier revoke): nothing left to do for it.
            log.info("revoked certificate %s for thing %s", certificate_id, thing_name)

    def _thing_principals(self, thing_name: str) -> list[str]:
        principals: list[str] = []
        kwargs: dict[str, Any] = {"thingName": thing_name}
        while True:
            try:
                page = self._client.list_thing_principals(**kwargs)
            except Exception as exc:
                if _error_code(exc) == _NOT_FOUND:
                    return []  # registered but never provisioned
                raise
            principals.extend(page.get("principals", []))
            token = page.get("nextToken")
            if not token:
                return principals
            kwargs["nextToken"] = token


def certificate_id_from_arn(principal: str) -> str | None:
    """``arn:aws:iot:<region>:<account>:cert/<id>`` -> ``<id>``; other principals -> None."""
    _, sep, certificate_id = principal.rpartition(":cert/")
    return certificate_id if sep and certificate_id else None


def _error_code(exc: Exception) -> str | None:
    """The AWS error code of a botocore ``ClientError``, without importing botocore."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    code = response.get("Error", {}).get("Code")
    return code if isinstance(code, str) else None
