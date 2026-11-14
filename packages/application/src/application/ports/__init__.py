"""Ports: interfaces the application needs from the outside world.

Concrete adapters live elsewhere: ``application.adapters.memory`` for local development/tests,
and (TODO) PostgreSQL / SQS / IoT Core / AppSync adapters for AWS.
"""

from application.ports.messaging import DeviceCommandPublisher, JobQueue, RealtimePublisher
from application.ports.repositories import (
    DeviceRepository,
    JobRepository,
    MembershipRepository,
    ProcessedMessageStore,
    ProjectRepository,
    RawDeviceMessageStore,
    SessionRepository,
    TelemetryRepository,
)

__all__ = [
    "DeviceCommandPublisher",
    "DeviceRepository",
    "JobQueue",
    "JobRepository",
    "MembershipRepository",
    "ProcessedMessageStore",
    "ProjectRepository",
    "RawDeviceMessageStore",
    "RealtimePublisher",
    "SessionRepository",
    "TelemetryRepository",
]
