"""Executes cloud-to-device commands from an explicit allowlist.

There is no generic "exec"/"shell" command and there must never be one: cloud input (including
AI-generated input) must not reach a shell on the board. Each command is a named Python
function with validated, scalar arguments.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from device_protocol.compat import UTC
from device_protocol.schemas import CommandPayload, CommandResultPayload, CommandResultStatus

CommandHandler = Callable[[dict[str, Any]], dict[str, Any]]


class CommandDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, name: str, handler: CommandHandler) -> None:
        if name in self._handlers:
            raise ValueError(f"command {name!r} already registered")
        self._handlers[name] = handler

    @property
    def allowed(self) -> list[str]:
        return sorted(self._handlers)

    def dispatch(
        self, command: CommandPayload, now: datetime | None = None
    ) -> CommandResultPayload:
        now = now or datetime.now(UTC)
        if command.is_expired(now):
            return self._result(command, CommandResultStatus.REJECTED, "command expired")
        handler = self._handlers.get(command.name)
        if handler is None:
            return self._result(command, CommandResultStatus.REJECTED, "command not allowed")
        try:
            output = handler(dict(command.args))
        except (ValueError, TypeError) as exc:
            return self._result(command, CommandResultStatus.REJECTED, f"bad arguments: {exc}")
        except Exception as exc:
            return self._result(command, CommandResultStatus.FAILED, type(exc).__name__)
        return CommandResultPayload(
            command_id=command.command_id, status=CommandResultStatus.SUCCEEDED, output=output
        )

    @staticmethod
    def _result(
        command: CommandPayload, status: CommandResultStatus, detail: str
    ) -> CommandResultPayload:
        return CommandResultPayload(command_id=command.command_id, status=status, detail=detail)
