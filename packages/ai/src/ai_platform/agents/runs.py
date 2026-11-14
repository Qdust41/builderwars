from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from domain.common import new_id, utcnow


class ApprovalState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(slots=True)
class ToolCallRecord:
    tool_name: str
    arguments: dict[str, Any]
    approval: ApprovalState
    outcome: str | None = None
    approved_by: str | None = None
    at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class AiRun:
    """Audit record of one AI run. Retention/privacy policy is open decision #8."""

    project_id: str
    requested_by: str
    prompt_reference: str  # pointer to stored input, not the raw prompt
    job_id: str | None = None
    id: str = field(default_factory=lambda: new_id("air"))
    output_reference: str | None = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)


class ModelProvider(Protocol):
    """Provider-agnostic model interface. No provider is chosen yet (open decision #8)."""

    def complete(
        self, *, system: str, messages: Sequence[dict[str, Any]], tools: Sequence[str]
    ) -> dict[str, Any]: ...
