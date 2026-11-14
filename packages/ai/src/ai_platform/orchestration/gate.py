"""Gate every model-requested tool call through allowlist, authorisation and approval checks.

* Unregistered tools are refused (there is no shell/exec tool to register).
* The acting human user must hold the tool's required permission on the project.
* READ_ONLY tools may run immediately.
* PROPOSAL and PRIVILEGED tools are recorded as PENDING; nothing executes until a human
  approves, and PRIVILEGED approvals additionally require ``APPROVE_FIRMWARE``.
* Every decision is written to the audit log.

TODO: executors for each tool, persistence of AiRun, approval API endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ai_platform.agents.runs import AiRun, ApprovalState, ToolCallRecord
from ai_platform.tools.base import ToolAccess, ToolCallRequest, ToolNotAllowedError, ToolRegistry
from domain.projects import Permission, ProjectRole, role_allows


class GateDecision(StrEnum):
    EXECUTE = "execute"
    AWAIT_APPROVAL = "await_approval"
    DENIED = "denied"


class AuditLog(Protocol):
    def record(self, *, run_id: str, project_id: str, event: str, detail: str) -> None: ...


class RoleLookup(Protocol):
    def role_of(self, user_id: str, project_id: str) -> ProjectRole | None: ...


@dataclass(frozen=True, slots=True)
class GateResult:
    decision: GateDecision
    reason: str
    record: ToolCallRecord | None = None


class ToolCallGate:
    def __init__(self, registry: ToolRegistry, roles: RoleLookup, audit: AuditLog) -> None:
        self._registry = registry
        self._roles = roles
        self._audit = audit

    def evaluate(self, run: AiRun, request: ToolCallRequest) -> GateResult:
        try:
            tool, _args = self._registry.validate_call(request)
        except ToolNotAllowedError as exc:
            return self._deny(run, request, str(exc))
        except ValueError as exc:  # pydantic ValidationError subclasses ValueError
            return self._deny(run, request, f"invalid arguments: {exc}")

        role = self._roles.role_of(run.requested_by, run.project_id)
        if not role_allows(role, tool.required_permission):
            return self._deny(run, request, "user lacks permission for this tool")

        if tool.access is ToolAccess.READ_ONLY:
            approval, decision = ApprovalState.NOT_REQUIRED, GateDecision.EXECUTE
        else:
            approval, decision = ApprovalState.PENDING, GateDecision.AWAIT_APPROVAL

        record = ToolCallRecord(request.tool_name, dict(request.arguments), approval)
        run.tool_calls.append(record)
        self._audit.record(
            run_id=run.id, project_id=run.project_id, event=decision.value, detail=tool.name
        )
        return GateResult(decision, f"{tool.access.value} tool", record)

    def approve(self, run: AiRun, record: ToolCallRecord, *, approver_id: str) -> None:
        if record.approval is not ApprovalState.PENDING:
            raise ValueError("only pending tool calls can be approved")
        tool = self._registry.get(record.tool_name)
        needed = (
            Permission.APPROVE_FIRMWARE
            if tool.access is ToolAccess.PRIVILEGED
            else tool.required_permission
        )
        if not role_allows(self._roles.role_of(approver_id, run.project_id), needed):
            self._audit.record(
                run_id=run.id,
                project_id=run.project_id,
                event="approval_denied",
                detail=f"{tool.name} by {approver_id}",
            )
            raise PermissionError(f"{approver_id} cannot approve {tool.name}")
        record.approval = ApprovalState.APPROVED
        record.approved_by = approver_id
        self._audit.record(
            run_id=run.id,
            project_id=run.project_id,
            event="approved",
            detail=f"{tool.name} by {approver_id}",
        )

    def _deny(self, run: AiRun, request: ToolCallRequest, reason: str) -> GateResult:
        self._audit.record(
            run_id=run.id,
            project_id=run.project_id,
            event="denied",
            detail=f"{request.tool_name}: {reason}",
        )
        return GateResult(GateDecision.DENIED, reason)
