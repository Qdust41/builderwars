from __future__ import annotations

from typing import Protocol

from application.realtime import RealtimeEvent
from device_protocol import DeviceEnvelope


class JobQueue(Protocol):
    """Hands a job to background workers (SQS in AWS). Messages carry only the job id."""

    def enqueue(self, job_id: str) -> None: ...


class CommandQueue(Protocol):
    """Hands a device command to the dispatcher worker (SQS in AWS). Carries only the id."""

    def enqueue_command(self, command_id: str) -> None: ...


class RealtimePublisher(Protocol):
    """Publishes notifications to session subscribers (AppSync Events in AWS).

    Events are notifications, not the source of truth: persist state first, then publish.
    """

    def publish(self, event: RealtimeEvent) -> None: ...


class DeviceCommandPublisher(Protocol):
    """Publishes an already-authorised command to a device (IoT Core in AWS).

    Only application services call this, after checking ``Permission.SEND_DEVICE_COMMAND``.
    The frontend never publishes device commands directly.
    """

    def publish_command(self, envelope: DeviceEnvelope) -> None: ...
