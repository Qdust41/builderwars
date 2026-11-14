from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from domain.projects import Permission


class ToolAccess(StrEnum):
    READ_ONLY = "read_only"  # inspects project data; no side effects
    PROPOSAL = "proposal"  # produces a proposal a human must approve; no direct side effects
    PRIVILEGED = "privileged"  # starts work that can affect hardware/firmware; needs approval


class ToolNotAllowedError(Exception):
    pass


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Tool:
    """Declarative tool definition exposed to a model.

    ``required_permission`` is checked against the *human* user on whose behalf the model acts;
    the model never has more access than that user.
    """

    name: str
    description: str
    access: ToolAccess
    input_model: type[BaseModel]
    required_permission: Permission


class ToolRegistry:
    """Allowlist of tools. Anything not registered cannot be called."""

    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolNotAllowedError(f"tool {name!r} is not registered") from None

    def names(self, *, access: set[ToolAccess] | None = None) -> list[str]:
        return sorted(n for n, t in self._tools.items() if access is None or t.access in access)

    def validate_call(self, request: ToolCallRequest) -> tuple[Tool, BaseModel]:
        tool = self.get(request.tool_name)
        return tool, tool.input_model.model_validate(request.arguments)
