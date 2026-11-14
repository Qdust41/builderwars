from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from application.adapters import memory
from application.services import (
    Authorizer,
    CommandService,
    DeviceMessageIngestService,
    DeviceService,
    JobService,
    ProjectService,
    SessionService,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "contracts" / "device" / "fixtures"


@dataclass
class World:
    projects_repo: memory.InMemoryProjectRepository
    memberships: memory.InMemoryMembershipRepository
    users: memory.InMemoryUserDirectory
    devices_repo: memory.InMemoryDeviceRepository
    sessions_repo: memory.InMemorySessionRepository
    jobs_repo: memory.InMemoryJobRepository
    queue: memory.InMemoryJobQueue
    realtime: memory.RecordingRealtimePublisher
    authorizer: Authorizer
    projects: ProjectService
    devices: DeviceService
    sessions: SessionService
    jobs: JobService
    commands_repo: memory.InMemoryDeviceCommandRepository
    command_queue: memory.InMemoryCommandQueue
    commands: CommandService


@pytest.fixture
def world() -> World:
    projects_repo = memory.InMemoryProjectRepository()
    memberships = memory.InMemoryMembershipRepository()
    users = memory.InMemoryUserDirectory()
    devices_repo = memory.InMemoryDeviceRepository()
    sessions_repo = memory.InMemorySessionRepository()
    jobs_repo = memory.InMemoryJobRepository()
    queue = memory.InMemoryJobQueue()
    realtime = memory.RecordingRealtimePublisher()
    authorizer = Authorizer(memberships)
    commands_repo = memory.InMemoryDeviceCommandRepository()
    command_queue = memory.InMemoryCommandQueue()
    return World(
        projects_repo=projects_repo,
        memberships=memberships,
        users=users,
        devices_repo=devices_repo,
        sessions_repo=sessions_repo,
        jobs_repo=jobs_repo,
        queue=queue,
        realtime=realtime,
        authorizer=authorizer,
        projects=ProjectService(projects_repo, memberships, authorizer, users),
        devices=DeviceService(devices_repo, authorizer),
        sessions=SessionService(sessions_repo, devices_repo, authorizer, realtime),
        jobs=JobService(jobs_repo, devices_repo, queue, authorizer),
        commands_repo=commands_repo,
        command_queue=command_queue,
        commands=CommandService(commands_repo, devices_repo, command_queue, authorizer),
    )


@dataclass
class IngestWorld:
    service: DeviceMessageIngestService
    devices: memory.InMemoryDeviceRepository
    raw: memory.InMemoryRawMessageStore
    telemetry: memory.InMemoryTelemetryRepository
    commands: memory.InMemoryDeviceCommandRepository


@pytest.fixture
def ingest() -> IngestWorld:
    devices = memory.InMemoryDeviceRepository()
    raw = memory.InMemoryRawMessageStore()
    telemetry = memory.InMemoryTelemetryRepository()
    commands = memory.InMemoryDeviceCommandRepository()
    service = DeviceMessageIngestService(
        devices=devices,
        processed=memory.InMemoryProcessedMessageStore(),
        raw_store=raw,
        telemetry=telemetry,
        sequences=memory.InMemorySequenceTracker(),
        commands=commands,
    )
    return IngestWorld(service, devices, raw, telemetry, commands)
