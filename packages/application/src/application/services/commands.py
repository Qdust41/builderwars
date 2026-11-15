"""Device command path (decision #5, spec 07).

API -> ``CommandService.request_command`` (authz ``device:command``, bounded per-device queue)
-> ``CommandQueue`` -> dispatcher worker publishes to ``devices/{id}/commands`` -> the device
answers with ``command_result`` -> ingest completes the command record.

Boards streaming through the signed-in CLI (ADR 0009) have no MQTT subscription, so the CLI
polls ``claim_for_device`` instead: it gets every pending command as the same envelope the
dispatcher would publish, and queued ones are marked sent. The result comes back through the
upload path like any other ``command_result``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from application.ports import CommandQueue, DeviceCommandRepository, DeviceRepository
from application.services.authorization import Authorizer
from application.services.device_events import DeviceEventPublisher
from device_protocol import DeviceEnvelope, MessageType, encode_message, topic_for_message
from domain.common import DomainError, NotFoundError, utcnow
from domain.devices import MAX_PENDING_COMMANDS_PER_DEVICE, DeviceCommand
from domain.projects import Permission


class CommandQueueFullError(DomainError):
    pass


class CommandService:
    def __init__(
        self,
        commands: DeviceCommandRepository,
        devices: DeviceRepository,
        queue: CommandQueue,
        authorizer: Authorizer,
        events: DeviceEventPublisher | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._commands = commands
        self._devices = devices
        self._queue = queue
        self._authorizer = authorizer
        self._events = events
        self._clock = clock

    def request_command(
        self,
        *,
        user_id: str,
        project_id: str,
        device_id: str,
        name: str,
        args: dict[str, float | int | bool | str],
    ) -> DeviceCommand:
        self._authorizer.require(user_id, project_id, Permission.SEND_DEVICE_COMMAND)
        device = self._devices.get(device_id)
        if device is None or device.project_id != project_id:
            raise NotFoundError("device", device_id)
        if self._commands.count_pending(device_id) >= MAX_PENDING_COMMANDS_PER_DEVICE:
            raise CommandQueueFullError(
                f"device {device_id} already has {MAX_PENDING_COMMANDS_PER_DEVICE} pending commands"
            )
        command = DeviceCommand(
            project_id=project_id,
            device_id=device_id,
            name=name,
            args=dict(args),
            requested_by=user_id,
        )
        # Persist first, then enqueue (TODO: transactional outbox, as for jobs).
        self._commands.add(command)
        self._queue.enqueue_command(command.id)
        # TODO (spec 08): audit-log every command with the acting user.
        return command

    def get_command(self, *, user_id: str, command_id: str) -> DeviceCommand:
        command = self._commands.get(command_id)
        if command is None:
            raise NotFoundError("command", command_id)
        try:
            self._authorizer.require(user_id, command.project_id, Permission.VIEW_PROJECT)
        except NotFoundError:
            raise NotFoundError("command", command_id) from None
        return self._expire(command)

    def claim_for_device(self, *, user_id: str, device_id: str) -> list[dict[str, Any]]:
        """Pending commands for a CLI-connected board, as ``{topic, payload}`` messages.

        Needs ``device:upload`` (whoever streams the board). Queued commands become sent;
        sent ones are returned again until answered, so a lost poll response is harmless
        (the host deduplicates by ``command_id``). Expired ones time out instead.
        """
        device = self._devices.get(device_id)
        if device is None:
            raise NotFoundError("device", device_id)
        try:
            self._authorizer.require(user_id, device.project_id, Permission.UPLOAD_DEVICE_DATA)
        except NotFoundError:
            raise NotFoundError("device", device_id) from None
        now = self._clock()
        out: list[dict[str, Any]] = []
        for command in self._commands.list_pending(device_id):
            command = self._expire(command, now)
            if not command.status.is_pending:
                continue
            envelope = DeviceEnvelope.new(
                device_id=device_id,
                message_type=MessageType.COMMAND,
                payload={
                    "command_id": str(UUID(command.id)),
                    "name": command.name,
                    "args": dict(command.args),
                    "expires_at": command.expires_at.isoformat() if command.expires_at else None,
                },
                timestamp=now,
            )
            if command.status.value == "queued":
                command = command.mark_sent(now)
                self._commands.save(command)
                self._notify(command)
            out.append(
                {
                    "topic": topic_for_message(device_id, MessageType.COMMAND),
                    "payload": json.loads(encode_message(envelope)),
                }
            )
        return out

    def _expire(self, command: DeviceCommand, now: datetime | None = None) -> DeviceCommand:
        """Time out a pending command nobody answered (no worker sweeps them)."""
        now = now or self._clock()
        if command.status.is_pending and command.is_expired(now):
            command = command.time_out(now)
            self._commands.save(command)
            self._notify(command)
        return command

    def _notify(self, command: DeviceCommand) -> None:
        if self._events is not None:
            self._events.command_updated(command)
