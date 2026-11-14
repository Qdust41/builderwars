"""Device revocation (spec 03) through the service, with the in-memory IoT fake."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from domain.common import InvalidStateTransitionError, NotFoundError, PermissionDeniedError
from domain.devices import ConnectionStatus, DeviceLifecycle
from domain.projects import ProjectMembership, ProjectRole

NOW = datetime(2026, 11, 14, 21, 0, tzinfo=UTC)


def _project_with_device(world):
    project = world.projects.create_project(user_id="alice", name="Rover")
    device = world.devices.register_device(
        user_id="alice", project_id=project.id, display_name="Bench", hardware_model="m"
    )
    world.provisioner.attach_certificate(device.id, "cert-1")
    return project, device


def _add(world, project_id: str, user: str, role: ProjectRole) -> None:
    world.memberships.add(ProjectMembership(project_id=project_id, user_id=user, role=role))


def test_owner_revokes_device_record_and_iot_certificate(world) -> None:
    _, device = _project_with_device(world)
    assert world.provisioner.can_connect(device.id)

    revoked = world.devices.revoke_device(user_id="alice", device_id=device.id, now=NOW)

    assert revoked.lifecycle is DeviceLifecycle.REVOKED
    assert revoked.revoked_at == NOW
    assert revoked.connection_status is ConnectionStatus.OFFLINE
    assert world.devices_repo.get(device.id) == revoked
    assert not world.provisioner.can_connect(device.id)


def test_revoke_is_idempotent_and_keeps_the_first_timestamp(world) -> None:
    _, device = _project_with_device(world)
    world.devices.revoke_device(user_id="alice", device_id=device.id, now=NOW)
    # A new certificate attached out of band is still revoked by a retry.
    world.provisioner.attach_certificate(device.id, "cert-2")
    again = world.devices.revoke_device(
        user_id="alice", device_id=device.id, now=NOW + timedelta(hours=1)
    )
    assert again.revoked_at == NOW
    assert not world.provisioner.can_connect(device.id)


def test_admin_may_revoke_but_member_and_viewer_may_not(world) -> None:
    project, device = _project_with_device(world)
    _add(world, project.id, "mia", ProjectRole.MEMBER)
    _add(world, project.id, "victor", ProjectRole.VIEWER)
    _add(world, project.id, "ada", ProjectRole.ADMIN)
    for user in ("mia", "victor"):
        with pytest.raises(PermissionDeniedError):
            world.devices.revoke_device(user_id=user, device_id=device.id)
    assert world.provisioner.can_connect(device.id)
    world.devices.revoke_device(user_id="ada", device_id=device.id)
    assert not world.provisioner.can_connect(device.id)


def test_non_member_gets_not_found_for_revoke(world) -> None:
    _, device = _project_with_device(world)
    with pytest.raises(NotFoundError, match="device"):
        world.devices.revoke_device(user_id="mallory", device_id=device.id)
    with pytest.raises(NotFoundError, match="device"):
        world.devices.revoke_device(user_id="alice", device_id="dev_missing")
    assert world.provisioner.can_connect(device.id)


def test_revoked_device_cannot_be_commanded(world) -> None:
    project, device = _project_with_device(world)
    world.devices.revoke_device(user_id="alice", device_id=device.id)
    with pytest.raises(InvalidStateTransitionError, match="revoked"):
        world.commands.request_command(
            user_id="alice", project_id=project.id, device_id=device.id, name="ping", args={}
        )
    assert world.command_queue.command_ids == []


def test_revoked_device_record_refuses_observations(world) -> None:
    _, device = _project_with_device(world)
    revoked = world.devices.revoke_device(user_id="alice", device_id=device.id)
    with pytest.raises(InvalidStateTransitionError):
        revoked.observed(NOW)
