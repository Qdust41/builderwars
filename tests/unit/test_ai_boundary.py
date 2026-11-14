from __future__ import annotations

import pytest

from ai_platform.agents import AiRun, ApprovalState
from ai_platform.context import REDACTED, redact
from ai_platform.orchestration import GateDecision, ToolCallGate
from ai_platform.tools import ToolAccess, ToolCallRequest, default_registry
from domain.projects import ProjectRole


class Roles:
    def __init__(self, roles: dict[str, ProjectRole]) -> None:
        self._roles = roles

    def role_of(self, user_id: str, project_id: str) -> ProjectRole | None:
        return self._roles.get(user_id)


class Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def record(self, *, run_id: str, project_id: str, event: str, detail: str) -> None:
        self.events.append((event, detail))


@pytest.fixture
def gate_and_audit():
    audit = Audit()
    roles = Roles(
        {"owner": ProjectRole.OWNER, "member": ProjectRole.MEMBER, "viewer": ProjectRole.VIEWER}
    )
    return ToolCallGate(default_registry(), roles, audit), audit


def _run(user: str) -> AiRun:
    return AiRun(project_id="p", requested_by=user, prompt_reference="s3://x")


def test_registry_has_no_shell_or_flash_tool() -> None:
    names = default_registry().names()
    assert not any(word in n for n in names for word in ("shell", "exec", "flash", "deploy"))
    assert set(default_registry().names(access={ToolAccess.READ_ONLY})) == {
        "read_project_file",
        "read_device_logs",
        "get_device_status",
    }


def test_unregistered_tool_is_denied_and_audited(gate_and_audit) -> None:
    gate, audit = gate_and_audit
    result = gate.evaluate(_run("owner"), ToolCallRequest(tool_name="run_shell", arguments={}))
    assert result.decision is GateDecision.DENIED
    assert audit.events[0][0] == "denied"


def test_read_only_tool_executes_without_approval(gate_and_audit) -> None:
    gate, _ = gate_and_audit
    run = _run("viewer")
    result = gate.evaluate(
        run, ToolCallRequest(tool_name="get_device_status", arguments={"device_id": "d"})
    )
    assert result.decision is GateDecision.EXECUTE
    assert run.tool_calls[0].approval is ApprovalState.NOT_REQUIRED


def test_non_member_cannot_use_any_tool(gate_and_audit) -> None:
    gate, _ = gate_and_audit
    result = gate.evaluate(
        _run("stranger"),
        ToolCallRequest(tool_name="get_device_status", arguments={"device_id": "d"}),
    )
    assert result.decision is GateDecision.DENIED


def test_path_traversal_arguments_are_denied(gate_and_audit) -> None:
    gate, _ = gate_and_audit
    result = gate.evaluate(
        _run("owner"),
        ToolCallRequest(
            tool_name="read_project_file", arguments={"project_id": "p", "path": "../../etc/passwd"}
        ),
    )
    assert result.decision is GateDecision.DENIED


def test_patch_proposal_waits_for_human_approval(gate_and_audit) -> None:
    gate, _ = gate_and_audit
    run = _run("member")
    result = gate.evaluate(
        run,
        ToolCallRequest(
            tool_name="propose_patch",
            arguments={"project_id": "p", "summary": "fix", "unified_diff": "--- a\n+++ b\n"},
        ),
    )
    assert result.decision is GateDecision.AWAIT_APPROVAL
    assert result.record is not None
    assert result.record.approval is ApprovalState.PENDING


def test_privileged_job_request_needs_firmware_approver(gate_and_audit) -> None:
    gate, audit = gate_and_audit
    run = _run("member")
    result = gate.evaluate(
        run,
        ToolCallRequest(
            tool_name="request_build_or_test_job",
            arguments={"project_id": "p", "job_type": "firmware_build"},
        ),
    )
    assert result.decision is GateDecision.AWAIT_APPROVAL
    with pytest.raises(PermissionError):
        gate.approve(run, result.record, approver_id="member")
    gate.approve(run, result.record, approver_id="owner")
    assert result.record.approval is ApprovalState.APPROVED
    assert ("approval_denied", "request_build_or_test_job by member") in audit.events


def test_redaction_strips_secret_keys_and_values() -> None:
    # Built at runtime so secret scanners do not flag this fake test value.
    marker = "PRIVATE" + " KEY"
    pem = f"-----BEGIN RSA {marker}-----\nabc\n-----END RSA {marker}-----"
    fake_key_id = "AKIA" + "ABCDEFGHIJKLMNOP"
    data = {
        "api_key": "sk-123",
        "nested": [{"password": "x", "note": f"key is {pem}"}],
        "log": f"creds {fake_key_id} leaked",
        "temperature_c": 42,
    }
    out = redact(data)
    assert out["api_key"] == REDACTED
    assert out["nested"][0]["password"] == REDACTED
    assert "PRIVATE KEY" not in out["nested"][0]["note"]
    assert "AKIA" not in out["log"]
    assert out["temperature_c"] == 42


def test_provider_config_modes() -> None:
    from ai_platform.providers import ProviderConfig, ProviderConfigError, ProviderMode

    bedrock = ProviderConfig.from_env({"AI_PROVIDER": "bedrock", "AI_MODEL": "some-model"})
    assert bedrock.mode is ProviderMode.BEDROCK
    assert bedrock.endpoint.startswith("https://bedrock-runtime.us-east-1.amazonaws.com")

    compatible = ProviderConfig.from_env(
        {"AI_MODEL": "m", "AI_BASE_URL": "http://localhost:11434/v1/", "AI_API_KEY_SECRET_ID": "s"}
    )
    assert compatible.endpoint == "http://localhost:11434/v1"

    with pytest.raises(ProviderConfigError, match="AI_MODEL"):
        ProviderConfig.from_env({"AI_PROVIDER": "bedrock"})
    with pytest.raises(ProviderConfigError, match="base_url"):
        ProviderConfig.from_env({"AI_MODEL": "m"})
    with pytest.raises(ProviderConfigError, match="IAM"):
        ProviderConfig.from_env(
            {"AI_PROVIDER": "bedrock", "AI_MODEL": "m", "AI_API_KEY_SECRET_ID": "s"}
        )


def test_viewer_cannot_run_ai_write_tools(gate_and_audit) -> None:
    gate, _ = gate_and_audit
    result = gate.evaluate(
        _run("viewer"),
        ToolCallRequest(
            tool_name="propose_patch",
            arguments={"project_id": "p", "summary": "x", "unified_diff": "x"},
        ),
    )
    assert result.decision is GateDecision.DENIED
