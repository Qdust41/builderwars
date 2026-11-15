"""Auto-fix: the error trigger (dedupe, caps), the fix worker, and its HTTP clients."""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
import pytest
from botocore.stub import ANY, Stubber

from ai_platform.autofix import (
    AnswerError,
    AutoFixWorker,
    GitHubRepository,
    PullRequest,
    RepoFile,
    parse_json_answer,
)
from ai_platform.http import HttpError, HttpResponse, ensure_public_endpoint
from ai_platform.providers.chat import ChatCompletionsClient
from application.adapters import memory
from application.ports import AutoFixSecrets
from application.services import (
    Authorizer,
    AutoFixLimitError,
    AutoFixNotReadyError,
    AutoFixService,
    AutoFixSettingsInput,
    AutoFixTrigger,
    AutoFixValidationError,
    DeviceMessageIngestService,
)
from aws_adapters import SecretsManagerAutoFixSecretStore, SqsAutoFixQueue
from device_protocol import DeviceEnvelope, MessageType, encode_message, topic_for_message
from domain.autofix import (
    AutoFixLevel,
    AutoFixRun,
    AutoFixRunStatus,
    AutoFixSettings,
    AutoFixTriggerKind,
    error_signature,
)
from domain.common import PermissionDeniedError
from domain.devices import Device
from domain.projects import ProjectMembership, ProjectRole

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


# --- fixtures -----------------------------------------------------------------------------------


@dataclass
class World:
    devices: memory.InMemoryDeviceRepository = field(
        default_factory=memory.InMemoryDeviceRepository
    )
    settings: memory.InMemoryAutoFixSettingsRepository = field(
        default_factory=memory.InMemoryAutoFixSettingsRepository
    )
    runs: memory.InMemoryAutoFixRunRepository = field(
        default_factory=memory.InMemoryAutoFixRunRepository
    )
    secrets: memory.InMemoryAutoFixSecretStore = field(
        default_factory=memory.InMemoryAutoFixSecretStore
    )
    queue: memory.InMemoryAutoFixQueue = field(default_factory=memory.InMemoryAutoFixQueue)
    telemetry: memory.InMemoryTelemetryRepository = field(
        default_factory=memory.InMemoryTelemetryRepository
    )
    memberships: memory.InMemoryMembershipRepository = field(
        default_factory=memory.InMemoryMembershipRepository
    )
    now: datetime = NOW

    def clock(self) -> datetime:
        return self.now

    def trigger(self) -> AutoFixTrigger:
        return AutoFixTrigger(
            settings=self.settings,
            runs=self.runs,
            queue=self.queue,
            devices=self.devices,
            clock=self.clock,
        )

    def service(self) -> AutoFixService:
        return AutoFixService(
            settings=self.settings,
            runs=self.runs,
            secrets=self.secrets,
            queue=self.queue,
            devices=self.devices,
            telemetry=self.telemetry,
            authorizer=Authorizer(self.memberships),
            clock=self.clock,
        )

    def configure(self, **overrides: Any) -> AutoFixSettings:
        settings = AutoFixSettings(
            project_id="prj_1",
            llm_base_url="https://llm.example.com/v1",
            llm_model="test-model",
            github_repo="acme/rig",
            updated_by="alice",
            has_github_token=True,
            has_llm_api_key=True,
            **overrides,
        )
        self.settings.save(settings)
        self.secrets.put("prj_1", AutoFixSecrets(llm_api_key="sk-test", github_token="ghp_x"))
        return settings


@pytest.fixture
def world() -> World:
    w = World()
    w.devices.add(
        Device(project_id="prj_1", display_name="Bench", hardware_model="freewili-1-og", id="dev_1")
    )
    for user, role in (("alice", ProjectRole.OWNER), ("bob", ProjectRole.MEMBER)):
        w.memberships.add(ProjectMembership(project_id="prj_1", user_id=user, role=role))
    return w


# --- domain -------------------------------------------------------------------------------------


def test_signature_ignores_numbers_ids_and_quoted_values() -> None:
    a = error_signature(
        "Timeout after 503 ms on 'COM3' (0x1F) id 3f2a9c1e-1111-2222-3333-abcdefabcdef"
    )
    b = error_signature(
        "timeout after 498 ms on 'COM4' (0xff) id 00000000-0000-0000-0000-000000000000"
    )
    assert a == b
    assert a != error_signature("sensor read failed")


def test_min_level_matches() -> None:
    assert AutoFixLevel.ERROR.matches("critical")
    assert AutoFixLevel.ERROR.matches("ERROR")
    assert not AutoFixLevel.ERROR.matches("warning")
    assert not AutoFixLevel.CRITICAL.matches("error")


# --- trigger ------------------------------------------------------------------------------------


def test_trigger_does_nothing_until_configured(world: World) -> None:
    assert world.trigger().on_device_error(device_id="dev_1", level="error", message="boom") is None
    assert world.queue.run_ids == []


def test_trigger_queues_one_run_per_distinct_error_per_window(world: World) -> None:
    world.configure()
    trigger = world.trigger()
    run = trigger.on_device_error(device_id="dev_1", level="error", message="I2C NACK at 0x40")
    assert run is not None
    assert run.trigger is AutoFixTriggerKind.ERROR_LOG
    assert run.requested_by is None
    assert world.queue.run_ids == [run.id]

    # Same error (different address): deduped. A different error: a new run.
    assert (
        trigger.on_device_error(device_id="dev_1", level="error", message="I2C NACK at 0x41")
        is None
    )
    assert (
        trigger.on_device_error(device_id="dev_1", level="critical", message="brownout") is not None
    )
    # After the dedupe window the same error may start a run again.
    world.now = NOW + timedelta(hours=25)
    assert trigger.on_device_error(device_id="dev_1", level="error", message="I2C NACK at 0x40")
    assert len(world.queue.run_ids) == 3


def test_trigger_respects_daily_cap_level_and_auto_switch(world: World) -> None:
    world.configure(max_runs_per_day=2)
    trigger = world.trigger()
    for i in range(5):
        trigger.on_device_error(
            device_id="dev_1", level="error", message=f"error kind {'abcde'[i]}"
        )
    assert len(world.queue.run_ids) == 2

    world.queue.run_ids.clear()
    world.now = NOW + timedelta(days=2)
    world.configure(min_level=AutoFixLevel.CRITICAL)
    assert trigger.on_device_error(device_id="dev_1", level="error", message="new one") is None
    world.configure(auto_trigger=False)
    assert trigger.on_device_error(device_id="dev_1", level="critical", message="new two") is None
    world.configure(enabled=False)
    assert trigger.on_device_error(device_id="dev_1", level="critical", message="new 3") is None
    assert world.queue.run_ids == []


def test_trigger_never_breaks_ingest(world: World) -> None:
    class Broken(memory.InMemoryAutoFixSettingsRepository):
        def get(self, project_id: str) -> AutoFixSettings | None:
            raise RuntimeError("db down")

    world.settings = Broken()
    assert world.trigger().on_device_error(device_id="dev_1", level="error", message="x") is None


def test_ingest_hands_new_errors_to_the_trigger(world: World) -> None:
    world.configure()
    ingest = DeviceMessageIngestService(
        devices=world.devices,
        processed=memory.InMemoryProcessedMessageStore(),
        raw_store=memory.InMemoryRawMessageStore(),
        telemetry=world.telemetry,
        sequences=memory.InMemorySequenceTracker(),
        errors=world.trigger(),
    )

    def send(kind: MessageType, payload: dict[str, Any]) -> bytes:
        env = DeviceEnvelope.new(
            device_id="dev_1", message_type=kind, payload=payload, timestamp=NOW
        )
        body = encode_message(env)
        ingest.ingest(topic=topic_for_message("dev_1", kind), body=body, received_at=NOW)
        return body

    send(MessageType.LOG, {"level": "info", "message": "booted"})
    send(MessageType.LOG, {"level": "warning", "message": "slow"})
    body = send(MessageType.LOG, {"level": "error", "message": "ADC stuck at 4095"})
    send(MessageType.EVENT, {"name": "board_disconnected", "severity": "error", "detail": "USB"})
    assert len(world.queue.run_ids) == 2
    runs = world.runs.list_for_project("prj_1", limit=10)
    assert {r.error_message for r in runs} == {"ADC stuck at 4095", "board_disconnected: USB"}

    # A duplicate delivery of the same message is not a new error.
    ingest.ingest(topic=topic_for_message("dev_1", MessageType.LOG), body=body, received_at=NOW)
    assert len(world.queue.run_ids) == 2


# --- settings + manual runs ---------------------------------------------------------------------


def _input(**overrides: Any) -> AutoFixSettingsInput:
    base: dict[str, Any] = {
        "llm_base_url": "https://api.openai.com/v1/",
        "llm_model": "gpt-test",
        "github_repo": "acme/rig",
    }
    return AutoFixSettingsInput(**(base | overrides))


def test_owner_saves_settings_and_keys_stay_in_the_secret_store(world: World) -> None:
    service = world.service()
    saved = service.save_settings(
        user_id="alice",
        project_id="prj_1",
        data=_input(llm_api_key="sk-1", github_token="ghp_1"),
    )
    assert saved.llm_base_url == "https://api.openai.com/v1"
    assert (saved.has_llm_api_key, saved.has_github_token, saved.ready) == (True, True, True)
    assert world.secrets.get("prj_1") == AutoFixSecrets("sk-1", "ghp_1")

    # Omitted keys are kept; "" clears one.
    again = service.save_settings(
        user_id="alice", project_id="prj_1", data=_input(llm_model="other", llm_api_key="")
    )
    assert world.secrets.get("prj_1") == AutoFixSecrets(None, "ghp_1")
    assert (again.has_llm_api_key, again.has_github_token) == (False, True)

    service.delete_settings(user_id="alice", project_id="prj_1")
    assert service.get_settings(user_id="bob", project_id="prj_1") is None
    assert world.secrets.get("prj_1") == AutoFixSecrets()


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"llm_base_url": "ftp://x"}, "http"),
        ({"llm_base_url": "https://user:pw@x.com/v1"}, "API key"),
        ({"github_repo": "not a repo"}, "owner/name"),
        ({"base_branch": "../main"}, "branch"),
        ({"max_runs_per_day": 0}, "max_runs_per_day"),
    ],
)
def test_settings_are_validated(world: World, overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(AutoFixValidationError, match=match):
        world.service().save_settings(user_id="alice", project_id="prj_1", data=_input(**overrides))


def test_members_cannot_change_settings(world: World) -> None:
    with pytest.raises(PermissionDeniedError):
        world.service().save_settings(user_id="bob", project_id="prj_1", data=_input())


def test_manual_run_uses_latest_error_and_skips_dedupe_not_cap(world: World) -> None:
    service = world.service()
    with pytest.raises(AutoFixNotReadyError):
        service.request_fix(user_id="bob", project_id="prj_1", device_id="dev_1", message="x")
    world.configure(max_runs_per_day=2)
    world.telemetry.add_log(
        device_id="dev_1", message_id="m1", at=NOW, level="error", message="old failure"
    )
    world.telemetry.add_log(
        device_id="dev_1", message_id="m2", at=NOW, level="info", message="fine"
    )
    run = service.request_fix(user_id="bob", project_id="prj_1", device_id="dev_1", message=None)
    assert (run.error_message, run.trigger, run.requested_by) == (
        "old failure",
        AutoFixTriggerKind.MANUAL,
        "bob",
    )
    # The automatic trigger now treats this error as recently handled.
    assert (
        world.trigger().on_device_error(device_id="dev_1", level="error", message="old failure")
        is None
    )
    service.request_fix(user_id="bob", project_id="prj_1", device_id="dev_1", message="old failure")
    with pytest.raises(AutoFixLimitError):
        service.request_fix(user_id="bob", project_id="prj_1", device_id=None, message="third")
    listed = service.list_runs(user_id="bob", project_id="prj_1")
    assert len(listed) == 2
    assert run.id in {r.id for r in listed}


# --- worker -------------------------------------------------------------------------------------


class FakeChat:
    model = "test-model"

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.prompts: list[Sequence[dict[str, str]]] = []

    def complete(self, messages: Sequence[dict[str, str]]) -> str:
        self.prompts.append(messages)
        return self.answers.pop(0)


class FakeRepo:
    repo = "acme/rig"

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files
        self.opened: list[dict[str, Any]] = []

    def default_branch(self) -> str:
        return "main"

    def branch_sha(self, branch: str) -> str:
        return f"sha-{branch}"

    def list_files(self, commit_sha: str) -> tuple[list[RepoFile], bool]:
        listed = [RepoFile(p, len(c)) for p, c in self.files.items()]
        listed.append(RepoFile("docs/logo.png", 10))
        listed.append(RepoFile("node_modules/x/index.js", 10))
        return listed, False

    def read_file(self, path: str, ref: str) -> str | None:
        return self.files.get(path)

    def open_pull_request(self, **kw: Any) -> PullRequest:
        self.opened.append(kw)
        return PullRequest(7, "https://github.com/acme/rig/pull/7")


FILES = {
    "host/sensors.py": "def read():\n    return adc.read(4096)\n",
    "host/main.py": "import sensors\n",
    ".github/workflows/ci.yml": "on: push\n",
}


def _queued(world: World, message: str = "ADC overflow: value 4096 > 4095") -> AutoFixRun:
    run = AutoFixRun(
        project_id="prj_1",
        trigger=AutoFixTriggerKind.ERROR_LOG,
        signature=error_signature(message),
        error_level="error",
        error_message=message,
        device_id="dev_1",
        created_at=NOW,
    )
    world.runs.add(run)
    return run


def _worker(world: World, chat: FakeChat, repo: FakeRepo) -> AutoFixWorker:
    return AutoFixWorker(
        runs=world.runs,
        settings=world.settings,
        secrets=world.secrets,
        telemetry=world.telemetry,
        clients=lambda settings, secrets: (chat, repo),
    )


PICK = json.dumps({"files": ["host/sensors.py", "../etc/passwd", "docs/logo.png"], "reason": "r"})


def _fix(*changes: tuple[str, str], fixable: bool = True) -> str:
    return json.dumps(
        {
            "fixable": fixable,
            "title": "Clamp ADC reads to 12 bits",
            "summary": "read() asked for 4096, one past the 12-bit max.",
            "changes": [{"path": p, "content": c} for p, c in changes],
        }
    )


def test_worker_opens_a_pull_request(world: World) -> None:
    world.configure(instructions="Board code lives in host/.")
    world.telemetry.add_log(
        device_id="dev_1",
        message_id="m1",
        at=NOW,
        level="info",
        message="token=abc AKIAABCDEFGHIJKLMNOP booted",
    )
    run = _queued(world)
    new = "def read():\n    return adc.read(4095)\n"
    chat = FakeChat(PICK, f"```json\n{_fix(('host/sensors.py', new))}\n```")
    repo = FakeRepo(dict(FILES))

    done = _worker(world, chat, repo).handle(run.id)

    assert done is not None
    assert done.status is AutoFixRunStatus.PR_OPENED, done.summary
    assert (done.pr_number, done.pr_url, done.branch) == (
        7,
        "https://github.com/acme/rig/pull/7",
        f"autofix/{run.id}",
    )
    assert done.files_changed == ("host/sensors.py",)
    assert (done.model, done.github_repo) == ("test-model", "acme/rig")

    [pr] = repo.opened
    assert pr["base_branch"] == "main"
    assert pr["base_sha"] == "sha-main"
    assert pr["changes"] == {"host/sensors.py": new}
    assert pr["title"] == "[auto-fix] Clamp ADC reads to 12 bits"
    assert "ADC overflow" in pr["body"]
    assert "has not been run or tested" in pr["body"]

    listing = chat.prompts[0][1]["content"]
    assert "host/sensors.py" in listing
    assert "docs/logo.png" not in listing
    assert "node_modules" not in listing
    assert "Board code lives in host/." in listing
    assert "AKIAABCDEFGHIJKLMNOP" not in listing  # redacted before it leaves
    second = chat.prompts[1][1]["content"]
    assert '<file path="host/sensors.py">' in second
    assert "host/main.py" not in second

    # Redelivery of the same message never opens a second pull request.
    assert _worker(world, FakeChat(), repo).handle(run.id) == done
    assert len(repo.opened) == 1


def test_worker_records_no_fix_and_rejects_unsafe_changes(world: World) -> None:
    world.configure()
    repo = FakeRepo(dict(FILES))

    run = _queued(world)
    done = _worker(world, FakeChat(PICK, _fix(fixable=False)), repo).handle(run.id)
    assert done is not None
    assert done.status is AutoFixRunStatus.NO_FIX
    assert "4096" in (done.summary or "")

    run = _queued(world)
    unsafe = _fix(
        (".github/workflows/ci.yml", "on: pull_request\n"),
        ("host/main.py", "import os\n"),  # exists but the model never read it
        ("uv.lock", "x"),
    )
    done = _worker(world, FakeChat(PICK, unsafe), repo).handle(run.id)
    assert done is not None
    assert done.status is AutoFixRunStatus.NO_FIX
    assert "CI workflows" in (done.summary or "")
    assert "had not read" in (done.summary or "")
    assert repo.opened == []


def test_worker_retries_bad_json_once_then_fails(world: World) -> None:
    world.configure()
    repo = FakeRepo(dict(FILES))
    run = _queued(world)
    new_file = ("host/limits.py", "MAX = 4095\n")
    done = _worker(world, FakeChat("sure!", PICK, _fix(new_file)), repo).handle(run.id)
    assert done is not None
    assert done.status is AutoFixRunStatus.PR_OPENED

    run = _queued(world)
    done = _worker(world, FakeChat("nope", "still nope"), repo).handle(run.id)
    assert done is not None
    assert done.status is AutoFixRunStatus.FAILED
    assert "no JSON" in (done.summary or "")


def test_worker_fails_cleanly(world: World) -> None:
    run = _queued(world)
    done = _worker(world, FakeChat(), FakeRepo({})).handle(run.id)
    assert done is not None
    assert done.status is AutoFixRunStatus.FAILED
    assert done.summary == "auto-fix was turned off for this project"

    world.configure()

    class Down(FakeRepo):
        def default_branch(self) -> str:
            raise HttpError("GitHub GET / failed: HTTP 401 (token invalid or expired)")

    run = _queued(world)
    done = _worker(world, FakeChat(), Down({})).handle(run.id)
    assert done is not None
    assert done.status is AutoFixRunStatus.FAILED
    assert "token invalid" in (done.summary or "")

    # A run left RUNNING by a worker that died is closed on redelivery.
    stuck = replace(
        _queued(world),
        status=AutoFixRunStatus.RUNNING,
        started_at=datetime.now(UTC) - timedelta(hours=1),
    )
    world.runs.save(stuck)
    done = _worker(world, FakeChat(), FakeRepo({})).handle(stuck.id)
    assert done is not None
    assert done.status is AutoFixRunStatus.FAILED


def test_parse_json_answer() -> None:
    assert parse_json_answer('Here:\n```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(AnswerError):
        parse_json_answer("[1, 2]")


# --- HTTP clients -------------------------------------------------------------------------------


@dataclass
class FakeTransport:
    responses: list[tuple[int, Any]]
    calls: list[tuple[str, str, dict[str, str], Any]] = field(default_factory=list)

    def request(
        self, method: str, url: str, *, headers: dict[str, str], body: bytes | None, timeout: float
    ) -> HttpResponse:
        self.calls.append((method, url, headers, json.loads(body) if body else None))
        status, payload = self.responses.pop(0)
        return HttpResponse(status, json.dumps(payload).encode())


def test_chat_client_speaks_openai_compatible() -> None:
    transport = FakeTransport([(200, {"choices": [{"message": {"content": "hi"}}]})])
    client = ChatCompletionsClient(
        base_url="https://llm.example.com/v1/", model="m", api_key="sk", transport=transport
    )
    assert client.complete([{"role": "user", "content": "x"}]) == "hi"
    [(method, url, headers, body)] = transport.calls
    assert (method, url) == ("POST", "https://llm.example.com/v1/chat/completions")
    assert headers["Authorization"] == "Bearer sk"
    assert body["model"] == "m"

    failing = ChatCompletionsClient(
        base_url="http://localhost:11434/v1",
        model="m",
        api_key=None,
        transport=FakeTransport([(401, {"error": "bad key"})]),
    )
    with pytest.raises(HttpError, match="HTTP 401"):
        failing.complete([])


def test_github_client_opens_pr_without_touching_base() -> None:
    transport = FakeTransport(
        [
            (200, {"tree": {"sha": "tree-0"}}),
            (201, {"sha": "tree-1"}),
            (201, {"sha": "commit-1"}),
            (201, {"ref": "refs/heads/autofix/x"}),
            (201, {"number": 3, "html_url": "https://github.com/acme/rig/pull/3"}),
        ]
    )
    repo = GitHubRepository("acme/rig", "ghp", transport=transport)
    pr = repo.open_pull_request(
        base_branch="main",
        base_sha="base",
        branch="autofix/x",
        changes={"a.py": "x = 1\n"},
        modes={"a.py": "100755"},
        commit_message="m",
        title="t",
        body="b",
    )
    assert pr == PullRequest(3, "https://github.com/acme/rig/pull/3")
    urls = [
        (c[0], c[1].removeprefix("https://api.github.com/repos/acme/rig")) for c in transport.calls
    ]
    assert urls == [
        ("GET", "/git/commits/base"),
        ("POST", "/git/trees"),
        ("POST", "/git/commits"),
        ("POST", "/git/refs"),
        ("POST", "/pulls"),
    ]
    assert transport.calls[1][3]["tree"][0]["mode"] == "100755"
    assert transport.calls[3][3]["ref"] == "refs/heads/autofix/x"
    assert transport.calls[4][3]["base"] == "main"
    assert transport.calls[0][2]["Authorization"] == "Bearer ghp"


def test_github_client_reads_files_and_explains_errors() -> None:
    content = base64.b64encode(b"print('hi')\n").decode()
    transport = FakeTransport(
        [
            (200, {"encoding": "base64", "content": content}),
            (404, {"message": "Not Found"}),
            (403, {"message": "Resource not accessible by personal access token"}),
        ]
    )
    repo = GitHubRepository("acme/rig", "ghp", transport=transport)
    assert repo.read_file("a b.py", "main") == "print('hi')\n"
    assert transport.calls[0][1].endswith("/contents/a%20b.py?ref=main")
    assert repo.read_file("missing.py", "main") is None
    with pytest.raises(HttpError, match="lacks permission"):
        repo.default_branch()


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:9001/v1", "http://169.254.169.254/latest", "http://10.0.0.5/v1"]
)
def test_deployed_workers_refuse_private_endpoints(url: str) -> None:
    with pytest.raises(HttpError, match="non-public"):
        ensure_public_endpoint(url)


# --- AWS adapters -------------------------------------------------------------------------------


def _sm() -> Any:
    return boto3.client(
        "secretsmanager",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


def test_secrets_manager_store_creates_reads_and_deletes() -> None:
    sm = _sm()
    store = SecretsManagerAutoFixSecretStore(sm, "builderwars/prod/autofix/")
    name = "builderwars/prod/autofix/prj_1"
    value = json.dumps({"llm_api_key": "sk", "github_token": "ghp"})
    with Stubber(sm) as stub:
        stub.add_client_error("get_secret_value", "ResourceNotFoundException")
        stub.add_client_error("put_secret_value", "ResourceNotFoundException")
        stub.add_response(
            "create_secret",
            {"Name": name},
            {
                "Name": name,
                "SecretString": value,
                "Description": ANY,
                "Tags": [{"Key": "project_id", "Value": "prj_1"}],
            },
        )
        stub.add_response("get_secret_value", {"SecretString": value}, {"SecretId": name})
        stub.add_response(
            "delete_secret", {}, {"SecretId": name, "ForceDeleteWithoutRecovery": True}
        )
        assert store.get("prj_1") == AutoFixSecrets()
        store.put("prj_1", AutoFixSecrets("sk", "ghp"))
        assert store.get("prj_1") == AutoFixSecrets("sk", "ghp")
        store.delete("prj_1")
        stub.assert_no_pending_responses()


def test_sqs_autofix_queue_sends_only_the_run_id() -> None:
    sqs = boto3.client(
        "sqs", region_name="us-east-1", aws_access_key_id="t", aws_secret_access_key="t"
    )
    with Stubber(sqs) as stub:
        stub.add_response(
            "send_message",
            {"MessageId": "1"},
            {"QueueUrl": "https://q", "MessageBody": json.dumps({"run_id": "fix_1"})},
        )
        SqsAutoFixQueue(sqs, "https://q").enqueue_autofix("fix_1")
        stub.assert_no_pending_responses()
