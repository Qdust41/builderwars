from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from domain.common import InvalidStateTransitionError
from domain.devices import ConnectionStatus, Device
from domain.firmware import ArtifactLocation, FirmwareArtifact
from domain.jobs import Job, JobStatus, JobType
from domain.projects import Permission, Project, ProjectRole, role_allows
from domain.sessions import Session


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        (ProjectRole.VIEWER, Permission.VIEW_PROJECT, True),
        (ProjectRole.VIEWER, Permission.START_SESSION, False),
        (ProjectRole.VIEWER, Permission.CREATE_JOB, False),
        (ProjectRole.MEMBER, Permission.CREATE_JOB, True),
        (ProjectRole.MEMBER, Permission.REGISTER_DEVICE, False),
        (ProjectRole.MEMBER, Permission.SEND_DEVICE_COMMAND, False),
        (ProjectRole.MEMBER, Permission.APPROVE_FIRMWARE, False),
        (ProjectRole.ADMIN, Permission.SEND_DEVICE_COMMAND, True),
        (ProjectRole.OWNER, Permission.APPROVE_FIRMWARE, True),
        (None, Permission.VIEW_PROJECT, False),
    ],
)
def test_role_permission_matrix(
    role: ProjectRole | None, permission: Permission, allowed: bool
) -> None:
    assert role_allows(role, permission) is allowed


def test_project_name_must_not_be_blank() -> None:
    with pytest.raises(ValueError, match="blank"):
        Project(name="   ", owner_user_id="u1")


def test_job_lifecycle_sets_timestamps() -> None:
    job = Job(project_id="p", job_type=JobType.TEST_RUN, created_by="u")
    running = job.transition(JobStatus.RUNNING)
    assert running.started_at is not None
    assert running.completed_at is None
    failed = running.transition(JobStatus.FAILED, error_summary="boom")
    assert failed.completed_at is not None
    assert failed.error_summary == "boom"


@pytest.mark.parametrize("terminal", [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED])
def test_terminal_jobs_cannot_transition(terminal: JobStatus) -> None:
    job = Job(project_id="p", job_type=JobType.AI_RUN, created_by="u")
    if terminal is JobStatus.SUCCEEDED:
        job = job.transition(JobStatus.RUNNING)
    done = job.transition(terminal)
    with pytest.raises(InvalidStateTransitionError):
        done.transition(JobStatus.RUNNING)


def test_queued_job_cannot_succeed_without_running() -> None:
    job = Job(project_id="p", job_type=JobType.AI_RUN, created_by="u")
    with pytest.raises(InvalidStateTransitionError):
        job.transition(JobStatus.SUCCEEDED)


def test_device_observation_ignores_older_messages() -> None:
    now = datetime(2026, 11, 14, 18, 30, tzinfo=UTC)
    device = Device(project_id="p", display_name="d", hardware_model="m").observed(now)
    stale = device.observed(now - timedelta(minutes=1), status=ConnectionStatus.OFFLINE)
    assert stale.last_seen_at == now
    assert stale.connection_status is ConnectionStatus.ONLINE


def test_device_observation_keeps_known_firmware_when_message_has_none() -> None:
    now = datetime(2026, 11, 14, 18, 30, tzinfo=UTC)
    device = Device(project_id="p", display_name="d", hardware_model="m", firmware_version="1.0")
    assert device.observed(now).firmware_version == "1.0"
    assert device.observed(now, firmware_version="1.1").firmware_version == "1.1"


def test_session_can_only_end_once() -> None:
    ended = Session(project_id="p", created_by="u").end()
    with pytest.raises(InvalidStateTransitionError):
        ended.end()


def test_firmware_artifact_validates_checksum_and_compatibility() -> None:
    loc = ArtifactLocation(bucket="b", key="k")
    with pytest.raises(ValueError, match="checksum"):
        FirmwareArtifact("p", "1.0", "not-a-sha", loc, frozenset({"m"}))
    with pytest.raises(ValueError, match="compatible"):
        FirmwareArtifact("p", "1.0", "a" * 64, loc, frozenset())
    artifact = FirmwareArtifact("p", "1.0", "a" * 64, loc, frozenset({"board-a"}))
    assert artifact.is_compatible_with("board-a")
    assert not artifact.is_compatible_with("board-b")
