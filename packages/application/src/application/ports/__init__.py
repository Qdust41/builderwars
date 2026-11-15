"""Ports: interfaces the application needs from the outside world.

Concrete adapters live elsewhere: ``application.adapters.memory`` for local development/tests,
``application.adapters.postgres`` for storage, and ``aws_adapters`` (packages/aws) for S3, SQS,
IoT Core and AppSync Events.
"""

from application.ports.messaging import (
    CommandQueue,
    DeviceCommandPublisher,
    JobQueue,
    RealtimePublisher,
)
from application.ports.repositories import (
    DeviceCommandRepository,
    DeviceLogEntry,
    DeviceRepository,
    JobRepository,
    MembershipRepository,
    ProcessedMessageStore,
    ProjectRepository,
    RawDeviceMessageStore,
    SequenceTracker,
    SessionRepository,
    TelemetryRepository,
    TelemetrySample,
    UserDirectory,
)

__all__ = [
    "CommandQueue",
    "DeviceCommandPublisher",
    "DeviceCommandRepository",
    "DeviceLogEntry",
    "DeviceRepository",
    "JobQueue",
    "JobRepository",
    "MembershipRepository",
    "ProcessedMessageStore",
    "ProjectRepository",
    "RawDeviceMessageStore",
    "RealtimePublisher",
    "SequenceTracker",
    "SessionRepository",
    "TelemetryRepository",
    "TelemetrySample",
    "UserDirectory",
]
