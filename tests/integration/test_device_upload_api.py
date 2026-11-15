"""Board data uploaded by a signed-in member (the builderwars CLI path), fanned out live."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.local_realtime import LocalRealtimeHub
from api.main import create_app
from api.settings import AppEnv, Settings
from board_runtime.cloud import Account, CloudApiTransport, CloudSession, login, read_messages
from board_runtime.config import DeviceConfig, TransportKind
from board_runtime.hardware import SimulatedSensors
from board_runtime.logging import CsvLogSink, DeviceLogForwarder
from board_runtime.main import BoardRuntime, app_log
from device_protocol import DeviceEnvelope, MessageType, encode_message, topic_for_message
from domain.devices import ConnectionStatus

pytestmark = pytest.mark.integration


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings(app_env=AppEnv.TEST)))


def _as(user: str) -> dict[str, str]:
    return {"X-Dev-User": user}


def _device(client: TestClient, owner: str = "alice") -> tuple[str, str]:
    pid = client.post("/projects", json={"name": "Rover"}, headers=_as(owner)).json()["id"]
    did = client.post(
        f"/projects/{pid}/devices", json={"display_name": "Bench"}, headers=_as(owner)
    ).json()["id"]
    return pid, did


def _message(device_id: str, kind: MessageType, payload: dict, *, topic_device: str = "") -> dict:
    env = DeviceEnvelope.new(
        device_id=device_id, message_type=kind, payload=payload, timestamp=datetime.now(UTC)
    )
    return {
        "topic": topic_for_message(topic_device or device_id, kind),
        "payload": json.loads(encode_message(env)),
    }


TELEMETRY = {"samples": [{"ts": "2026-11-15T09:00:00+00:00", "readings": {"temp_c": 21.5}}]}


def _hub(client: TestClient) -> LocalRealtimeHub:
    hub = client.app.state.container.local.realtime  # type: ignore[attr-defined]
    assert isinstance(hub, LocalRealtimeHub)
    return hub


def test_uploaded_messages_are_stored_and_published_live(client: TestClient) -> None:
    pid, did = _device(client)
    messages = [
        _message(did, MessageType.TELEMETRY, TELEMETRY),
        _message(did, MessageType.LOG, {"level": "info", "message": "booted"}),
    ]
    response = client.post(
        f"/devices/{did}/messages", json={"messages": messages}, headers=_as("alice")
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["processed"], body["duplicate"], body["rejected"]) == (2, 0, 0)

    samples = client.get(f"/devices/{did}/telemetry", headers=_as("alice")).json()
    assert samples[0]["readings"] == {"temp_c": 21.5}
    [log] = client.get(f"/devices/{did}/logs", headers=_as("alice")).json()
    assert log["message"] == "booted"

    channel = client.get(f"/devices/{did}/channel", headers=_as("alice")).json()["channel"]
    published = [e for e in _hub(client).published if e.channel == channel]
    assert [e.type.value for e in published] == [
        "device.status_changed",  # the device came online
        "device.telemetry",
        "device.log",
    ]

    # Uploading the same messages again (a retry, or a file that overlaps) stores nothing new.
    again = client.post(
        f"/devices/{did}/messages", json={"messages": messages}, headers=_as("alice")
    ).json()
    assert (again["processed"], again["duplicate"]) == (0, 2)
    assert len(client.get(f"/devices/{did}/logs", headers=_as("alice")).json()) == 1
    assert pid


def test_an_upload_cannot_write_into_another_device(client: TestClient) -> None:
    pid, did = _device(client)
    other = client.post(
        f"/projects/{pid}/devices", json={"display_name": "Other"}, headers=_as("alice")
    ).json()["id"]
    messages = [
        # Topic names the other device.
        _message(other, MessageType.LOG, {"level": "info", "message": "x"}),
        # Topic says this device, envelope says the other one.
        _message(other, MessageType.LOG, {"level": "info", "message": "y"}, topic_device=did),
        {"topic": f"devices/{did}/commands", "payload": {}},
    ]
    body = client.post(
        f"/devices/{did}/messages", json={"messages": messages}, headers=_as("alice")
    ).json()
    assert body["rejected"] == 3
    assert [r["reason"] for r in body["results"]] == [
        "identity_mismatch",
        "identity_mismatch",
        "wrong_channel",
    ]
    for device in (did, other):
        assert client.get(f"/devices/{device}/logs", headers=_as("alice")).json() == []


def test_upload_needs_the_member_role(client: TestClient) -> None:
    pid, did = _device(client)
    message = {"messages": [_message(did, MessageType.LOG, {"level": "info", "message": "x"})]}
    # Not in the project: the device does not exist as far as they can tell.
    assert (
        client.post(f"/devices/{did}/messages", json=message, headers=_as("mallory")).status_code
        == 404
    )
    client.get("/projects", headers=_as("vic"))  # registers vic@example.com
    client.get("/projects", headers=_as("meg"))
    for user, role in (("vic", "viewer"), ("meg", "member")):
        added = client.post(
            f"/projects/{pid}/members",
            json={"email": f"{user}@example.com", "role": role},
            headers=_as("alice"),
        )
        assert added.status_code == 201, added.text
    assert (
        client.post(f"/devices/{did}/messages", json=message, headers=_as("vic")).status_code == 403
    )
    assert (
        client.post(f"/devices/{did}/messages", json=message, headers=_as("meg")).status_code == 200
    )
    assert (
        client.post("/devices/dev_missing/messages", json=message, headers=_as("alice")).status_code
        == 404
    )


def test_upload_size_is_bounded(client: TestClient) -> None:
    _, did = _device(client)
    one = _message(did, MessageType.LOG, {"level": "info", "message": "x"})
    for messages in ([], [one] * 201):
        response = client.post(
            f"/devices/{did}/messages", json={"messages": messages}, headers=_as("alice")
        )
        assert response.status_code == 422


def test_client_config_is_public_and_names_the_auth_mode(client: TestClient) -> None:
    assert client.get("/client-config").json() == {
        "environment": "test",
        "auth_mode": "dev-header",
        "cognito_region": None,
        "cognito_user_pool_id": None,
        "cognito_app_client_id": None,
    }


# -- the CLI side, against the same app ----------------------------------------------------
def _send_via(client: TestClient):  # type: ignore[no-untyped-def]
    def send(method: str, url: str, headers: dict, body: bytes | None, timeout: float):  # type: ignore[no-untyped-def]
        path = url.removeprefix("http://localhost:8000")
        response = client.request(method, path, headers=headers, content=body)
        return response.status_code, response.content

    return send


def test_cli_login_run_and_upload_reach_the_dashboard(client: TestClient, tmp_path: Path) -> None:
    _, did = _device(client)
    send = _send_via(client)
    account = login(
        api_url="http://localhost:8000/",
        email="alice",
        password=lambda: pytest.fail("a dev API never asks for a password"),
        new_password=lambda: "",
        state_dir=tmp_path,
        send=send,
    )
    assert account.auth_mode == "dev-header"
    assert Account.load(tmp_path).api_url == "http://localhost:8000"
    assert (tmp_path / "account.json").stat().st_mode & 0o077 == 0  # private to the user

    # `builderwars run --cloud`: the runtime publishes through the API as alice.
    session = CloudSession.load(tmp_path, send=send)
    csv_path = tmp_path / "logs" / f"{did}.csv"
    config = DeviceConfig(
        device_id=did,
        hardware_model="freewili",
        firmware_version="1.0.0",
        transport=TransportKind.CLOUD,
        batch_max_samples=2,
    )
    runtime = BoardRuntime(
        config,
        CloudApiTransport(session, did),
        SimulatedSensors(seed=1),
        csv_sink=CsvLogSink(csv_path),
    )
    runtime.start()
    for _ in range(4):
        runtime.sample()
    runtime.send_log({"level": "warning", "message": "fan stalled"})
    runtime.stop()
    assert runtime.buffer.peek() is None  # everything was delivered

    assert len(client.get(f"/devices/{did}/telemetry", headers=_as("alice")).json()) == 4
    logs = client.get(f"/devices/{did}/logs", headers=_as("alice")).json()
    assert [entry["message"] for entry in logs] == ["fan stalled"]
    types = {e.type.value for e in _hub(client).published}
    assert {"device.telemetry", "device.log"} <= types

    # `builderwars upload <csv>`: the same logs again are recognised, not duplicated.
    read = read_messages(csv_path, did)
    assert read.skipped == []
    assert len(read.messages) == 1
    result = CloudApiTransport(session, did).upload(read.messages)
    assert (result["processed"], result["duplicate"]) == (0, 1)


def test_upload_readdresses_files_recorded_under_a_local_id(
    client: TestClient, tmp_path: Path
) -> None:
    _, did = _device(client)
    lines = [
        _message("dev-local", MessageType.TELEMETRY, TELEMETRY),
        _message("dev-local", MessageType.LOG, {"level": "info", "message": "hi"}),
        {"topic": "devices/dev-local/commands", "payload": {}},  # cloud -> board: skipped
    ]
    path = tmp_path / "run.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\nnot json\n")
    read = read_messages(path, did)
    assert len(read.messages) == 2
    assert read.skipped == [
        "line 4: not a board message (Expecting value: line 1 column 1 (char 0))"
    ]
    assert {m["payload"]["device_id"] for m in read.messages} == {did}

    login(
        api_url="http://localhost:8000",
        email="alice",
        password=str,
        new_password=str,
        state_dir=tmp_path,
        send=_send_via(client),
    )
    session = CloudSession.load(tmp_path, send=_send_via(client))
    result = CloudApiTransport(session, did).upload(read.messages)
    assert result["processed"] == 2


def test_cli_logs_downloads_the_cloud_history_to_csv(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from board_runtime import cli
    from board_runtime.cloud import CLOUD_LOG_COLUMNS

    _, did = _device(client)
    send = _send_via(client)
    login(
        api_url="http://localhost:8000",
        email="alice",
        password=str,
        new_password=str,
        state_dir=tmp_path,
        send=send,
    )
    monkeypatch.setattr(cli, "_session", lambda state_dir: CloudSession.load(state_dir, send=send))
    monkeypatch.setattr("board_runtime.cloud.logs.PAGE_SIZE", 2)  # force several pages
    messages = [
        _message(did, MessageType.LOG, {"level": "info", "message": f"line {i}, with comma"})
        for i in range(5)
    ]
    CloudApiTransport(CloudSession.load(tmp_path, send=send), did).upload(messages)
    monkeypatch.chdir(tmp_path)

    # By device name; default output file next to where you run it.
    assert cli.main(["--state-dir", str(tmp_path), "logs", "bench"]) == 0
    out = tmp_path / f"{did}-logs.csv"
    with out.open(newline="") as handle:
        rows = list(csv.reader(handle))
    assert tuple(rows[0]) == CLOUD_LOG_COLUMNS
    assert [r[4] for r in rows[1:]] == [f"line {i}, with comma" for i in range(5)]
    assert {r[1] for r in rows[1:]} == {did}
    assert "5 entries" in capsys.readouterr().out

    # An existing file is not overwritten without --force; stdout works with -o -.
    assert cli.main(["--state-dir", str(tmp_path), "logs", did]) == 2
    assert cli.main(["--state-dir", str(tmp_path), "logs", did, "-o", "-"]) == 0
    assert capsys.readouterr().out.count("with comma") == 5
    assert cli.main(["--state-dir", str(tmp_path), "logs", did, "--since", "2999-01-01"]) == 2
    assert (
        cli.main(["--state-dir", str(tmp_path), "logs", did, "--since", "2999-01-01", "--force"])
        == 0
    )
    assert out.read_text().count("\n") == 1  # header only

    # Unknown devices and not-signed-in say what to do.
    assert cli.main(["--state-dir", str(tmp_path), "logs", "nope"]) == 1
    assert "builderwars devices" in capsys.readouterr().err
    assert cli.main(["--state-dir", str(tmp_path), "logout"]) == 0
    assert cli.main(["--state-dir", str(tmp_path), "logs", did, "--force"]) == 1
    assert "builderwars login" in capsys.readouterr().err


def test_dashboard_commands_reach_a_cli_board_and_status_follows_the_run(
    client: TestClient, tmp_path: Path
) -> None:
    pid, did = _device(client)
    send = _send_via(client)
    login(
        api_url="http://localhost:8000/",
        email="alice",
        password=lambda: pytest.fail("no password in dev mode"),
        new_password=lambda: "",
        state_dir=tmp_path,
        send=send,
    )
    session = CloudSession.load(tmp_path, send=send)
    config = DeviceConfig(
        device_id=did,
        hardware_model="freewili",
        firmware_version="1.0.0",
        transport=TransportKind.CLOUD,
    )
    transport = CloudApiTransport(session, did, poll_interval_s=None)  # polled by hand below
    runtime = BoardRuntime(config, transport, SimulatedSensors(seed=1))
    forwarder = DeviceLogForwarder(runtime.send_log)  # as run_loop does
    app_log.addHandler(forwarder)
    app_log.setLevel(logging.INFO)

    assert client.get(f"/devices/{did}", headers=_as("alice")).json()["connection_status"] == (
        "unknown"
    )
    runtime.start()
    assert client.get(f"/devices/{did}", headers=_as("alice")).json()["connection_status"] == (
        "online"
    )

    sent = client.post(
        f"/projects/{pid}/devices/{did}/commands", json={"name": "ping"}, headers=_as("alice")
    ).json()
    assert sent["status"] == "queued"
    assert transport.poll_commands() == 1
    assert transport.poll_commands() == 0  # answered: nothing pending any more
    command = client.get(f"/commands/{sent['id']}", headers=_as("alice")).json()
    assert command["status"] == "succeeded"
    assert command["output"] == {"pong": True}
    messages = [
        e["message"] for e in client.get(f"/devices/{did}/logs", headers=_as("alice")).json()
    ]
    assert "received command ping from the dashboard" in messages
    assert "command ping: succeeded" in messages
    updates = [
        e.data["status"]
        for e in _hub(client).published
        if e.type.value == "device.command.updated" and e.data["command_id"] == sent["id"]
    ]
    assert updates == ["sent", "succeeded"]

    runtime.stop()
    app_log.removeHandler(forwarder)
    assert client.get(f"/devices/{did}", headers=_as("alice")).json()["connection_status"] == (
        "offline"
    )
    statuses = [
        e.data["connection_status"]
        for e in _hub(client).published
        if e.type.value == "device.status_changed"
    ]
    assert statuses == ["online", "offline"]


def test_unanswered_commands_time_out(client: TestClient) -> None:
    pid, did = _device(client)
    container = client.app.state.container  # type: ignore[attr-defined]
    sent = client.post(
        f"/projects/{pid}/devices/{did}/commands", json={"name": "ping"}, headers=_as("alice")
    ).json()
    stored = container.commands._commands.get(sent["id"])
    container.commands._commands.save(
        replace(stored, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    assert client.get(f"/commands/{sent['id']}", headers=_as("alice")).json()["status"] == (
        "timed_out"
    )
    claimed = client.post(f"/devices/{did}/commands/claim", headers=_as("alice")).json()
    assert claimed == {"messages": []}


def test_a_silent_device_reads_as_offline(client: TestClient) -> None:
    _, did = _device(client)
    container = client.app.state.container  # type: ignore[attr-defined]
    devices = container.devices._devices
    device = devices.get(did)
    devices.save(
        replace(
            device,
            connection_status=ConnectionStatus.ONLINE,
            last_seen_at=datetime.now(UTC) - timedelta(minutes=5),
        )
    )
    assert client.get(f"/devices/{did}", headers=_as("alice")).json()["connection_status"] == (
        "offline"
    )
    devices.save(
        replace(device, connection_status=ConnectionStatus.ONLINE, last_seen_at=datetime.now(UTC))
    )
    assert (
        client.get(f"/devices/{did}/status", headers=_as("alice")).json()["connection_status"]
        == "online"
    )
