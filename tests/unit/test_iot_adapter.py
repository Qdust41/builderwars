"""The AWS IoT provisioning adapter against a mocked boto3 ``iot`` client. No AWS calls."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from api.adapters.iot import IotDeviceIdentityProvisioner, certificate_id_from_arn

ARN = "arn:aws:iot:us-east-1:000000000000:cert/{}"


class FakeClientError(Exception):
    """Shaped like botocore's ClientError, which the adapter recognises by ``response``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


def test_revoke_revokes_and_detaches_every_certificate_across_pages() -> None:
    client = MagicMock()
    client.list_thing_principals.side_effect = [
        {"principals": [ARN.format("aaa")], "nextToken": "t1"},
        {"principals": [ARN.format("bbb"), "arn:aws:cognito-identity:x:y:z"]},
    ]
    IotDeviceIdentityProvisioner(client).revoke("dev_1")

    assert client.list_thing_principals.call_args_list == [
        call(thingName="dev_1"),
        call(thingName="dev_1", nextToken="t1"),
    ]
    assert client.update_certificate.call_args_list == [
        call(certificateId="aaa", newStatus="REVOKED"),
        call(certificateId="bbb", newStatus="REVOKED"),
    ]
    assert client.detach_thing_principal.call_args_list == [
        call(thingName="dev_1", principal=ARN.format("aaa")),
        call(thingName="dev_1", principal=ARN.format("bbb")),
    ]


def test_revoke_of_a_never_provisioned_device_is_a_no_op() -> None:
    client = MagicMock()
    client.list_thing_principals.side_effect = FakeClientError("ResourceNotFoundException")
    IotDeviceIdentityProvisioner(client).revoke("dev_1")
    client.update_certificate.assert_not_called()


def test_revoke_tolerates_a_certificate_already_removed() -> None:
    client = MagicMock()
    client.list_thing_principals.return_value = {"principals": [ARN.format("aaa")]}
    client.detach_thing_principal.side_effect = FakeClientError("ResourceNotFoundException")
    IotDeviceIdentityProvisioner(client).revoke("dev_1")
    client.update_certificate.assert_called_once()


@pytest.mark.parametrize("step", ["list_thing_principals", "update_certificate"])
def test_other_aws_errors_propagate_so_the_revoke_can_be_retried(step: str) -> None:
    client = MagicMock()
    client.list_thing_principals.return_value = {"principals": [ARN.format("aaa")]}
    getattr(client, step).side_effect = FakeClientError("ThrottlingException")
    with pytest.raises(FakeClientError):
        IotDeviceIdentityProvisioner(client).revoke("dev_1")


def test_certificate_id_from_arn() -> None:
    assert certificate_id_from_arn(ARN.format("abc123")) == "abc123"
    assert certificate_id_from_arn("arn:aws:iam::0:role/x") is None
    assert certificate_id_from_arn("arn:aws:iot:r:a:cert/") is None
