"""Send one queued device command to its device (decision #5, spec 07).

Shared by the dispatcher worker (SQS -> IoT Core) and the local development bridge.
Idempotent: a command that is no longer ``queued`` is skipped, so a redelivery never publishes
twice. Expired commands time out instead of being sent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from application.ports import DeviceCommandPublisher, DeviceCommandRepository
from application.services.device_events import DeviceEventPublisher
from device_protocol import DeviceEnvelope, MessageType
from domain.devices import CommandStatus, DeviceCommand


class CommandDispatchService:
    def __init__(
        self,
        commands: DeviceCommandRepository,
        publisher: DeviceCommandPublisher,
        events: DeviceEventPublisher | None = None,
    ) -> None:
        self._commands = commands
        self._publisher = publisher
        self._events = events

    def dispatch(self, command_id: str, now: datetime | None = None) -> DeviceCommand | None:
        now = now or datetime.now(UTC)
        command = self._commands.get(command_id)
        if command is None or command.status is not CommandStatus.QUEUED:
            return command
        if command.is_expired(now):
            timed_out = command.time_out(now)
            self._commands.save(timed_out)
            self._notify(timed_out)
            return timed_out

        envelope = DeviceEnvelope.new(
            device_id=command.device_id,
            message_type=MessageType.COMMAND,
            payload={
                "command_id": str(UUID(command.id)),
                "name": command.name,
                "args": dict(command.args),
                "expires_at": command.expires_at.isoformat() if command.expires_at else None,
            },
            timestamp=now,
        )
        # Publish first, then mark sent: a crash in between re-publishes on redelivery and the
        # host answers both with the same command_id, which the cloud deduplicates.
        self._publisher.publish_command(envelope)
        sent = command.mark_sent(now)
        self._commands.save(sent)
        self._notify(sent)
        return sent

    def _notify(self, command: DeviceCommand) -> None:
        if self._events is not None:
            self._events.command_updated(command)
