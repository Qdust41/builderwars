"""Port contract tests: every repository adapter behaves the same, in memory and in PostgreSQL."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from application.adapters import memory
from domain.common import ConflictError
from domain.devices import (
    CommandStatus,
    ConnectionStatus,
    Device,
    DeviceCommand,
    DeviceSetup,
    Sensor,
    TargetBoard,
)
from domain.jobs import Job, JobStatus, JobType
from domain.projects import Project, ProjectMembership, ProjectRole
from domain.sessions import Session

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 14, 12, 0, 0, 123456, tzinfo=UTC)


@pytest.fixture
def repos(backend: str, request: pytest.FixtureRequest) -> Any:
    if backend == "postgres":
        return request.getfixturevalue("pg")
    return SimpleNamespace(
        projects=memory.InMemoryProjectRepository(),
        memberships=memory.InMemoryMembershipRepository(),
        devices=memory.InMemoryDeviceRepository(),
        sessions=memory.InMemorySessionRepository(),
        jobs=memory.InMemoryJobRepository(),
        commands=memory.InMemoryDeviceCommandRepository(),
        processed=memory.InMemoryProcessedMessageStore(),
        sequences=memory.InMemorySequenceTracker(),
        setups=memory.InMemoryDeviceSetupRepository(),
        sensors=(sensors := memory.InMemorySensorRepository()),
        boards=memory.InMemoryTargetBoardRepository(sensors),
    )


def _project(repos: Any, name: str = "Rover", at: datetime = T0) -> Project:
    project = Project(name=name, owner_user_id="alice", created_at=at, updated_at=at)
    repos.projects.add(project)
    return project


def _device(repos: Any, project_id: str, at: datetime = T0) -> Device:
    device = Device(
        project_id=project_id,
        display_name="Bench board",
        hardware_model="freewili-1-og",
        extensions=frozenset({"bottlenose-wifi-orca", "a-ext"}),
        created_at=at,
    )
    repos.devices.add(device)
    return device


def test_projects_round_trip_and_list_by_ids_keeps_requested_order(repos: Any) -> None:
    a = _project(repos, "A")
    b = _project(repos, "B", T0 + timedelta(seconds=1))
    assert repos.projects.get(a.id) == a
    assert repos.projects.get("prj_missing") is None
    assert [p.id for p in repos.projects.list_by_ids([b.id, "prj_missing", a.id])] == [b.id, a.id]
    assert repos.projects.list_by_ids([]) == []


def test_memberships_are_keyed_by_project_and_user(repos: Any) -> None:
    p1, p2 = _project(repos, "A"), _project(repos, "B")
    repos.memberships.add(ProjectMembership(p1.id, "bob", ProjectRole.VIEWER, created_at=T0))
    repos.memberships.add(
        ProjectMembership(p2.id, "bob", ProjectRole.MEMBER, created_at=T0 + timedelta(seconds=1))
    )
    # Re-adding the same (project, user) replaces the role.
    repos.memberships.add(ProjectMembership(p1.id, "bob", ProjectRole.ADMIN, created_at=T0))
    assert repos.memberships.get(p1.id, "bob").role is ProjectRole.ADMIN
    assert repos.memberships.get(p1.id, "carol") is None
    assert [m.project_id for m in repos.memberships.list_for_user("bob")] == [p1.id, p2.id]
    assert repos.memberships.list_for_user("carol") == []

    repos.memberships.add(
        ProjectMembership(p1.id, "carol", ProjectRole.MEMBER, created_at=T0 + timedelta(seconds=2))
    )
    assert [m.user_id for m in repos.memberships.list_for_project(p1.id)] == ["bob", "carol"]
    repos.memberships.remove(p1.id, "bob")
    repos.memberships.remove(p1.id, "nobody")  # removing a non-member is a no-op
    assert repos.memberships.get(p1.id, "bob") is None
    assert [m.user_id for m in repos.memberships.list_for_project(p1.id)] == ["carol"]
    assert [m.project_id for m in repos.memberships.list_for_user("bob")] == [p2.id]


def test_devices_round_trip_save_and_list_for_project(repos: Any) -> None:
    project, other = _project(repos), _project(repos, "Other")
    device = _device(repos, project.id)
    _device(repos, other.id)
    assert repos.devices.get(device.id) == device

    seen = device.observed(T0 + timedelta(minutes=1), firmware_version="1.2.3")
    repos.devices.save(seen)
    stored = repos.devices.get(device.id)
    assert stored.connection_status is ConnectionStatus.ONLINE
    assert stored.firmware_version == "1.2.3"
    assert stored.last_seen_at == T0 + timedelta(minutes=1)
    assert stored.extensions == frozenset({"bottlenose-wifi-orca", "a-ext"})
    assert [d.id for d in repos.devices.list_for_project(project.id)] == [device.id]


def test_sessions_round_trip(repos: Any) -> None:
    project = _project(repos)
    device = _device(repos, project.id)
    session = Session(project_id=project.id, created_by="alice", device_id=device.id, created_at=T0)
    repos.sessions.add(session)
    assert repos.sessions.get(session.id) == session
    assert repos.sessions.list_for_project(project.id) == [session]
    assert repos.sessions.get("ses_missing") is None


def test_jobs_round_trip_and_status_transitions_persist(repos: Any) -> None:
    project = _project(repos)
    job = Job(project_id=project.id, job_type=JobType.TEST_RUN, created_by="alice", created_at=T0)
    repos.jobs.add(job)
    assert repos.jobs.get(job.id) == job

    running = job.transition(JobStatus.RUNNING)
    repos.jobs.save(running)
    failed = replace(running.transition(JobStatus.FAILED, error_summary="boom"))
    repos.jobs.save(failed)
    assert repos.jobs.get(job.id) == failed
    assert repos.jobs.get("job_missing") is None


def test_commands_round_trip_and_count_pending(repos: Any) -> None:
    project = _project(repos)
    device = _device(repos, project.id)
    other = _device(repos, project.id)

    def new(device_id: str) -> DeviceCommand:
        command = DeviceCommand(
            project_id=project.id,
            device_id=device_id,
            name="set_led",
            requested_by="alice",
            args={"on": True, "level": 3, "ratio": 0.5, "color": "red"},
            created_at=T0,
        )
        repos.commands.add(command)
        return command

    queued, sent, done = new(device.id), new(device.id), new(device.id)
    new(other.id)
    repos.commands.save(sent.mark_sent(T0))
    finished = done.mark_sent(T0).complete(
        CommandStatus.SUCCEEDED, now=T0 + timedelta(seconds=2), output={"pong": True}
    )
    repos.commands.save(finished)

    assert repos.commands.get(queued.id) == queued
    assert repos.commands.get(done.id) == finished
    assert repos.commands.get("missing") is None
    assert repos.commands.count_pending(device.id) == 2
    assert repos.commands.count_pending("dev_unknown") == 0


def test_processed_message_keys_are_marked_exactly_once(repos: Any) -> None:
    assert repos.processed.mark_processed("dev-1:m1") is True
    assert repos.processed.mark_processed("dev-1:m1") is False
    assert repos.processed.mark_processed("dev-2:m1") is True


def test_processed_message_marking_is_atomic_under_concurrency(repos: Any) -> None:
    results: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)

    def worker() -> None:
        barrier.wait()
        ok = repos.processed.mark_processed("dev-1:race")
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False, False, False, True]


def test_sequence_tracker_reports_gaps_only_going_forward(repos: Any) -> None:
    seq = repos.sequences
    assert seq.observe("dev-1", 10) == 0  # first message
    assert seq.observe("dev-1", 11) == 0  # contiguous
    assert seq.observe("dev-1", 14) == 2  # 12 and 13 missing
    assert seq.observe("dev-1", 13) == 0  # late arrival, not a new gap
    assert seq.observe("dev-1", 14) == 0  # duplicate
    assert seq.observe("dev-1", 16) == 1  # high-water mark stayed at 14
    assert seq.observe("dev-2", 0) == 0  # per device


# --- device setup: laptop -> FREE-WILi -> target boards, and sensors --------------------------


def test_device_setup_round_trips(repos: Any) -> None:
    device = _device(repos, _project(repos).id)
    assert repos.setups.get(device.id) is None
    setup = DeviceSetup(device_id=device.id, updated_at=T0).with_report(
        host={"hostname": "bench", "os": "Linux"},
        bridge={"model": "FREE-WILi", "serial": "FW1"},
        by="alice",
        at=T0,
    )
    repos.setups.save(setup)
    assert repos.setups.get(device.id) == setup
    again = setup.with_report(host={"hostname": "other"}, bridge=None, by="bob", at=T0)
    repos.setups.save(again)
    assert repos.setups.get(device.id) == again
    locked = again.claim_run("run_abc", by="bob", at=T0)
    repos.setups.save(locked)
    assert repos.setups.get(device.id) == locked
    repos.setups.save(locked.release_run("run_abc", at=T0))
    assert repos.setups.get(device.id).run_id is None


def _sensor(device_id: str, board_id: str, key: str, at: datetime = T0) -> Sensor:
    return Sensor(
        device_id=device_id,
        board_id=board_id,
        key=key,
        name=key.title(),
        bus={"protocol": "i2c", "address": 72, "reg": 0, "length": 2, "setup_writes": []},
        decode={"data_type": "i16_be", "bit_shift": 4, "scale": 0.0625},
        unit="°C",
        poll_interval_s=2.5,
        created_at=at,
        updated_at=at,
    )


def test_boards_and_sensors_round_trip_and_cascade(repos: Any) -> None:
    device = _device(repos, _project(repos).id)
    a = TargetBoard(device_id=device.id, name="A", created_at=T0, updated_at=T0)
    b = TargetBoard(
        device_id=device.id, name="B", created_at=T0 + timedelta(seconds=1), updated_at=T0
    )
    repos.boards.add(b)
    repos.boards.add(a)
    assert [x.name for x in repos.boards.list_for_device(device.id)] == ["A", "B"]
    repos.boards.save(replace(a, name="A2", notes="rev 2"))
    assert repos.boards.get(a.id).notes == "rev 2"

    temp = _sensor(device.id, a.id, "temp")
    volts = _sensor(device.id, b.id, "volts", T0 + timedelta(seconds=1))
    repos.sensors.add(temp)
    repos.sensors.add(volts)
    assert repos.sensors.get(temp.id) == temp
    assert [s.key for s in repos.sensors.list_for_device(device.id)] == ["temp", "volts"]

    with pytest.raises(ConflictError):
        repos.sensors.add(_sensor(device.id, b.id, "temp"))
    with pytest.raises(ConflictError):
        repos.sensors.save(replace(volts, key="temp"))

    repos.sensors.save(replace(temp, board_id=b.id, enabled=False))
    assert repos.sensors.get(temp.id).enabled is False

    repos.boards.delete(b.id)  # takes its sensors with it
    assert repos.sensors.list_for_device(device.id) == []
    repos.sensors.add(_sensor(device.id, a.id, "again"))
    repos.sensors.delete(repos.sensors.list_for_device(device.id)[0].id)
    assert repos.sensors.list_for_device(device.id) == []
