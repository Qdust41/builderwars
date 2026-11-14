"""Ports: interfaces the application needs from the outside world.

Concrete adapters live elsewhere: ``application.adapters.memory`` for local development/tests,
and (TODO) PostgreSQL / SQS / IoT Core / AppSync adapters for AWS.
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
