"""Dispatch queued device commands to IoT Core (decision #5, spec 07).

Queue messages carry only ``{"command_id": ...}``. The dispatch rules (idempotency, expiry)
live in ``application.services.CommandDispatchService``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from application.ports import DeviceCommandPublisher, DeviceCommandRepository
from application.services import CommandDispatchService, DeviceEventPublisher
from domain.devices import DeviceCommand


class CommandMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: str


class CommandDispatchHandler:
    def __init__(
        self,
        commands: DeviceCommandRepository,
        publisher: DeviceCommandPublisher,
        events: DeviceEventPublisher | None = None,
    ) -> None:
        self._service = CommandDispatchService(commands, publisher, events)

    def handle(self, message: CommandMessage, now: datetime | None = None) -> DeviceCommand | None:
        return self._service.dispatch(message.command_id, now)
