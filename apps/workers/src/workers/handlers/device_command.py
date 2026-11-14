"""Dispatch queued device commands to IoT Core (decision #5, spec 07).

Queue messages carry only ``{"command_id": ...}``. Idempotent: a command that is no longer
``queued`` is skipped, so a redelivery never publishes twice. Expired commands time out
instead of being sent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from application.ports import DeviceCommandPublisher, DeviceCommandRepository
from device_protocol import DeviceEnvelope, MessageType
from domain.devices import CommandStatus, DeviceCommand


class CommandMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: str


class CommandDispatchHandler:
    def __init__(
        self, commands: DeviceCommandRepository, publisher: DeviceCommandPublisher
    ) -> None:
        self._commands = commands
        self._publisher = publisher

    def handle(self, message: CommandMessage, now: datetime | None = None) -> DeviceCommand | None:
        now = now or datetime.now(UTC)
        command = self._commands.get(message.command_id)
        if command is None or command.status is not CommandStatus.QUEUED:
            return command
        if command.is_expired(now):
            timed_out = command.time_out(now)
            self._commands.save(timed_out)
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
        return sent
