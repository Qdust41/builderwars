"""Device command path (decision #5, spec 07).

API -> ``CommandService.request_command`` (authz ``device:command``, bounded per-device queue)
-> ``CommandQueue`` -> dispatcher worker publishes to ``devices/{id}/commands`` -> the device
answers with ``command_result`` -> ingest completes the command record.
"""

from __future__ import annotations

from application.ports import CommandQueue, DeviceCommandRepository, DeviceRepository
from application.services.authorization import Authorizer
from domain.common import DomainError, NotFoundError
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
    ) -> None:
        self._commands = commands
        self._devices = devices
        self._queue = queue
        self._authorizer = authorizer

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
        return command
