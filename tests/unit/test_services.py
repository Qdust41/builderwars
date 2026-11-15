from __future__ import annotations

import pytest

from application.realtime import RealtimeEventType, session_channel
from domain.common import NotFoundError, PermissionDeniedError
from domain.jobs import JobType
from domain.projects import ProjectMembership, ProjectRole


def _add(world, project_id: str, user: str, role: ProjectRole) -> None:
    world.memberships.add(ProjectMembership(project_id=project_id, user_id=user, role=role))


def test_creating_a_project_makes_the_creator_owner(world) -> None:
    project = world.projects.create_project(user_id="alice", name="Rover")
    assert world.authorizer.role_of("alice", project.id) is ProjectRole.OWNER
    assert [p.id for p in world.projects.list_projects(user_id="alice")] == [project.id]
    assert world.projects.list_projects(user_id="bob") == []


def test_non_members_get_not_found_not_forbidden(world) -> None:
    project = world.projects.create_project(user_id="alice", name="Rover")
    with pytest.raises(NotFoundError):
        world.projects.get_project(user_id="mallory", project_id=project.id)
    with pytest.raises(NotFoundError):
        world.devices.list_devices(user_id="mallory", project_id=project.id)


def test_viewer_cannot_register_devices_or_create_jobs(world) -> None:
    project = world.projects.create_project(user_id="alice", name="Rover")
    _add(world, project.id, "victor", ProjectRole.VIEWER)
    assert world.projects.get_project(user_id="victor", project_id=project.id) == project
    with pytest.raises(PermissionDeniedError):
        world.devices.register_device(
            user_id="victor", project_id=project.id, display_name="b", hardware_model="m"
        )
    with pytest.raises(PermissionDeniedError):
        world.jobs.create_job(user_id="victor", project_id=project.id, job_type=JobType.TEST_RUN)
    assert world.queue.job_ids == []


def test_member_job_is_persisted_then_enqueued(world) -> None:
    project = world.projects.create_project(user_id="alice", name="Rover")
    _add(world, project.id, "mia", ProjectRole.MEMBER)
    job = world.jobs.create_job(user_id="mia", project_id=project.id, job_type=JobType.TEST_RUN)
    assert world.jobs_repo.get(job.id) == job
    assert world.queue.job_ids == [job.id]


def test_device_from_another_project_is_rejected(world) -> None:
    a = world.projects.create_project(user_id="alice", name="A")
    b = world.projects.create_project(user_id="alice", name="B")
    device = world.devices.register_device(
        user_id="alice", project_id=b.id, display_name="board", hardware_model="m"
    )
    with pytest.raises(NotFoundError):
        world.sessions.start_session(user_id="alice", project_id=a.id, device_id=device.id)
    with pytest.raises(NotFoundError):
        world.jobs.create_job(
            user_id="alice", project_id=a.id, job_type=JobType.TEST_RUN, device_id=device.id
        )


def test_session_start_publishes_activity_event(world) -> None:
    project = world.projects.create_project(user_id="alice", name="A")
    session = world.sessions.start_session(user_id="alice", project_id=project.id)
    [event] = world.realtime.events
    assert event.type is RealtimeEventType.PROJECT_ACTIVITY
    assert event.channel == session_channel(project.id, session.id)
    assert "_" not in event.channel  # AppSync Events channel segments: [A-Za-z0-9-] only


def test_device_lookup_hides_devices_of_other_projects(world) -> None:
    project = world.projects.create_project(user_id="alice", name="A")
    device = world.devices.register_device(
        user_id="alice", project_id=project.id, display_name="b", hardware_model="m"
    )
    with pytest.raises(NotFoundError, match="device"):
        world.devices.get_device(user_id="mallory", device_id=device.id)


def _project_with_device(world):
    project = world.projects.create_project(user_id="alice", name="Bench")
    device = world.devices.register_device(
        user_id="alice", project_id=project.id, display_name="b", hardware_model="freewili-1-og"
    )
    return project, device


def test_admin_command_is_persisted_then_queued(world) -> None:
    project, device = _project_with_device(world)
    _add(world, project.id, "ada", ProjectRole.ADMIN)
    command = world.commands.request_command(
        user_id="ada", project_id=project.id, device_id=device.id, name="ping", args={}
    )
    assert world.commands_repo.get(command.id) == command
    assert world.command_queue.command_ids == [command.id]
    assert world.commands.get_command(user_id="ada", command_id=command.id) == command


def test_members_and_viewers_cannot_command_devices(world) -> None:
    project, device = _project_with_device(world)
    _add(world, project.id, "mia", ProjectRole.MEMBER)
    with pytest.raises(PermissionDeniedError):
        world.commands.request_command(
            user_id="mia", project_id=project.id, device_id=device.id, name="ping", args={}
        )
    with pytest.raises(NotFoundError):
        world.commands.request_command(
            user_id="mallory", project_id=project.id, device_id=device.id, name="ping", args={}
        )


def test_per_device_command_queue_is_bounded(world) -> None:
    from application.services import CommandQueueFullError
    from domain.devices import MAX_PENDING_COMMANDS_PER_DEVICE

    project, device = _project_with_device(world)
    for _ in range(MAX_PENDING_COMMANDS_PER_DEVICE):
        world.commands.request_command(
            user_id="alice", project_id=project.id, device_id=device.id, name="ping", args={}
        )
    with pytest.raises(CommandQueueFullError):
        world.commands.request_command(
            user_id="alice", project_id=project.id, device_id=device.id, name="ping", args={}
        )
