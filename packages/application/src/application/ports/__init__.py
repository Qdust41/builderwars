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
from application.ports.provisioning import DeviceIdentityProvisioner
from application.ports.repositories import (
    DeviceCommandRepository,
    DeviceRepository,
    JobRepository,
    MembershipRepository,
    ProcessedMessageStore,
    ProjectRepository,
    RawDeviceMessageStore,
    SequenceTracker,
    SessionRepository,
    TelemetryRepository,
)

__all__ = [
    "CommandQueue",
    "DeviceCommandPublisher",
    "DeviceCommandRepository",
    "DeviceIdentityProvisioner",
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
]
