"""Ports: interfaces the application needs from the outside world.

Concrete adapters live elsewhere: ``application.adapters.memory`` for local development/tests,
``application.adapters.postgres`` for storage, and ``aws_adapters`` (packages/aws) for S3, SQS,
IoT Core and AppSync Events.
"""

from application.ports.autofix import (
    AutoFixQueue,
    AutoFixRunRepository,
    AutoFixSecrets,
    AutoFixSecretStore,
    AutoFixSettingsRepository,
)
from application.ports.messaging import (
    CommandQueue,
    DeviceCommandPublisher,
    JobQueue,
    RealtimePublisher,
)
from application.ports.repositories import (
    DeviceCommandRepository,
    DeviceLogEntry,
    DeviceLogRecord,
    DeviceRepository,
    DeviceSetupRepository,
    JobRepository,
    LogPosition,
    MembershipRepository,
    ProcessedMessageStore,
    ProjectRepository,
    RawDeviceMessageStore,
    SensorRepository,
    SequenceTracker,
    SessionRepository,
    TargetBoardRepository,
    TelemetryRepository,
    TelemetrySample,
    UserDirectory,
)

__all__ = [
    "AutoFixQueue",
    "AutoFixRunRepository",
    "AutoFixSecretStore",
    "AutoFixSecrets",
    "AutoFixSettingsRepository",
    "CommandQueue",
    "DeviceCommandPublisher",
    "DeviceCommandRepository",
    "DeviceLogEntry",
    "DeviceLogRecord",
    "DeviceRepository",
    "DeviceSetupRepository",
    "JobQueue",
    "JobRepository",
    "LogPosition",
    "MembershipRepository",
    "ProcessedMessageStore",
    "ProjectRepository",
    "RawDeviceMessageStore",
    "RealtimePublisher",
    "SensorRepository",
    "SequenceTracker",
    "SessionRepository",
    "TargetBoardRepository",
    "TelemetryRepository",
    "TelemetrySample",
    "UserDirectory",
]
