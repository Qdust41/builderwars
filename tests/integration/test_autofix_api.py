"""Auto-fix over HTTP: settings (keys write-only), uploaded errors queue runs, manual runs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.settings import AppEnv, Settings
from application.adapters import memory
from device_protocol import DeviceEnvelope, MessageType, encode_message, topic_for_message

pytestmark = pytest.mark.integration


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings(app_env=AppEnv.TEST)))


def _as(user: str) -> dict[str, str]:
    return {"X-Dev-User": user}


def _setup(client: TestClient) -> tuple[str, str]:
    client.get("/projects", headers=_as("bob"))  # dev-header mode registers bob on first call
    pid = client.post("/projects", json={"name": "Rover"}, headers=_as("alice")).json()["id"]
    did = client.post(
        f"/projects/{pid}/devices", json={"display_name": "Bench"}, headers=_as("alice")
    ).json()["id"]
    client.post(
        f"/projects/{pid}/members",
        json={"email": "bob@example.com", "role": "member"},
        headers=_as("alice"),
    )
    return pid, did


def _queue(client: TestClient) -> memory.InMemoryAutoFixQueue:
    queue = client.app.state.container.autofix._queue  # type: ignore[attr-defined]
    assert isinstance(queue, memory.InMemoryAutoFixQueue)
    return queue


def _log(device_id: str, level: str, message: str) -> dict[str, Any]:
    env = DeviceEnvelope.new(
        device_id=device_id,
        message_type=MessageType.LOG,
        payload={"level": level, "message": message},
        timestamp=datetime.now(UTC),
    )
    return {
        "topic": topic_for_message(device_id, MessageType.LOG),
        "payload": json.loads(encode_message(env)),
    }


SETTINGS = {
    "llm_base_url": "https://api.openai.com/v1",
    "llm_model": "gpt-test",
    "github_repo": "acme/rig",
    "llm_api_key": "sk-secret",
    "github_token": "ghp_secret",
}


def test_settings_are_admin_only_and_never_return_keys(client: TestClient) -> None:
    pid, _ = _setup(client)
    assert client.get(f"/projects/{pid}/autofix", headers=_as("alice")).status_code == 404

    response = client.put(f"/projects/{pid}/autofix", json=SETTINGS, headers=_as("alice"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["has_llm_api_key"] is True
    assert body["has_github_token"] is True
    assert body["ready"] is True
    assert "secret" not in response.text

    bad = client.put(
        f"/projects/{pid}/autofix", json=SETTINGS | {"github_repo": "nope"}, headers=_as("alice")
    )
    assert bad.status_code == 422

    assert client.get(f"/projects/{pid}/autofix", headers=_as("bob")).status_code == 200
    assert (
        client.put(f"/projects/{pid}/autofix", json=SETTINGS, headers=_as("bob")).status_code == 403
    )
    assert client.get(f"/projects/{pid}/autofix", headers=_as("mallory")).status_code == 404

    assert client.delete(f"/projects/{pid}/autofix", headers=_as("alice")).status_code == 204
    assert client.get(f"/projects/{pid}/autofix", headers=_as("alice")).status_code == 404


def test_uploaded_error_logs_queue_one_run(client: TestClient) -> None:
    pid, did = _setup(client)
    client.put(f"/projects/{pid}/autofix", json=SETTINGS, headers=_as("alice"))

    messages = [
        _log(did, "info", "booted"),
        _log(did, "error", "I2C NACK from 0x40"),
        _log(did, "error", "I2C NACK from 0x41"),  # same error, deduped
    ]
    response = client.post(
        f"/devices/{did}/messages", json={"messages": messages}, headers=_as("alice")
    )
    assert response.status_code == 200, response.text

    [run] = client.get(f"/projects/{pid}/autofix/runs", headers=_as("bob")).json()
    assert run["status"] == "queued"
    assert run["trigger"] == "error_log"
    assert run["error_message"] == "I2C NACK from 0x40"
    assert run["device_id"] == did
    assert _queue(client).run_ids == [run["id"]]
    one = client.get(f"/projects/{pid}/autofix/runs/{run['id']}", headers=_as("bob"))
    assert one.json()["id"] == run["id"]


def test_members_can_ask_for_a_fix(client: TestClient) -> None:
    pid, did = _setup(client)
    early = client.post(
        f"/projects/{pid}/autofix/runs", json={"device_id": did}, headers=_as("bob")
    )
    assert early.status_code == 409
    assert early.json()["code"] == "autofix_not_ready"

    client.put(
        f"/projects/{pid}/autofix",
        json=SETTINGS | {"auto_trigger": False, "max_runs_per_day": 1},
        headers=_as("alice"),
    )
    client.post(
        f"/devices/{did}/messages",
        json={"messages": [_log(did, "critical", "brownout on 3V3 rail")]},
        headers=_as("alice"),
    )
    assert _queue(client).run_ids == []  # auto_trigger is off

    response = client.post(
        f"/projects/{pid}/autofix/runs", json={"device_id": did}, headers=_as("bob")
    )
    assert response.status_code == 202, response.text
    run = response.json()
    assert (run["trigger"], run["requested_by"], run["error_level"]) == (
        "manual",
        "bob",
        "critical",
    )
    assert run["error_message"] == "brownout on 3V3 rail"

    capped = client.post(
        f"/projects/{pid}/autofix/runs", json={"message": "another"}, headers=_as("bob")
    )
    assert capped.status_code == 409
    assert capped.json()["code"] == "autofix_daily_limit"
