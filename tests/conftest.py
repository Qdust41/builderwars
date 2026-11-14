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
from domain.devices import Device

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "contracts" / "device" / "fixtures"


@dataclass
class World:
    projects_repo: memory.InMemoryProjectRepository
    memberships: memory.InMemoryMembershipRepository
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
    provisioner: memory.InMemoryDeviceIdentityProvisioner


@pytest.fixture
def world() -> World:
    projects_repo = memory.InMemoryProjectRepository()
    memberships = memory.InMemoryMembershipRepository()
    devices_repo = memory.InMemoryDeviceRepository()
    sessions_repo = memory.InMemorySessionRepository()
    jobs_repo = memory.InMemoryJobRepository()
    queue = memory.InMemoryJobQueue()
    realtime = memory.RecordingRealtimePublisher()
    authorizer = Authorizer(memberships)
    commands_repo = memory.InMemoryDeviceCommandRepository()
    command_queue = memory.InMemoryCommandQueue()
    provisioner = memory.InMemoryDeviceIdentityProvisioner()
    return World(
        projects_repo=projects_repo,
        memberships=memberships,
        devices_repo=devices_repo,
        sessions_repo=sessions_repo,
        jobs_repo=jobs_repo,
        queue=queue,
        realtime=realtime,
        authorizer=authorizer,
        projects=ProjectService(projects_repo, memberships, authorizer),
        devices=DeviceService(devices_repo, authorizer, provisioner),
        sessions=SessionService(sessions_repo, devices_repo, authorizer, realtime),
        jobs=JobService(jobs_repo, devices_repo, queue, authorizer),
        commands_repo=commands_repo,
        command_queue=command_queue,
        commands=CommandService(commands_repo, devices_repo, command_queue, authorizer),
        provisioner=provisioner,
    )


@dataclass
class IngestWorld:
    service: DeviceMessageIngestService
    devices: memory.InMemoryDeviceRepository
    raw: memory.InMemoryRawMessageStore
    telemetry: memory.InMemoryTelemetryRepository
    commands: memory.InMemoryDeviceCommandRepository


INGEST_DEVICE_IDS = ("dev-1", "dev-2")


@pytest.fixture
def ingest() -> IngestWorld:
    """Ingest pipeline with ``dev-1`` and ``dev-2`` registered (ingest refuses unknown ids)."""
    devices = memory.InMemoryDeviceRepository()
    for device_id in INGEST_DEVICE_IDS:
        devices.add(
            Device(
                id=device_id,
                project_id="prj_test",
                display_name=device_id,
                hardware_model="freewili-1-og",
            )
        )
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
