"""Device dashboard reads and the LOCAL-ONLY bridge a simulated host uses (no AWS)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.settings import AppEnv, Settings
from device_protocol import DeviceEnvelope, MessageType, encode_message, topic_for_message

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


def _host_message(client: TestClient, device_id: str, kind: MessageType, payload: dict) -> dict:
    env = DeviceEnvelope.new(
        device_id=device_id, message_type=kind, payload=payload, timestamp=datetime.now(UTC)
    )
    body = {"topic": topic_for_message(device_id, kind), "payload": json.loads(encode_message(env))}
    response = client.post("/local/device-messages", json=body)
    assert response.status_code == 200
    return response.json()


def test_host_messages_show_up_in_telemetry_and_logs(client: TestClient) -> None:
    _, did = _device(client)
    batch = {
        "samples": [
            {
                "ts": "2026-11-14T20:00:00+00:00",
                "readings": {"temperature_c": 40.5, "button": True},
            },
            {
                "ts": "2026-11-14T20:00:01+00:00",
                "readings": {"temperature_c": 41.0, "button": False},
            },
        ]
    }
    assert _host_message(client, did, MessageType.TELEMETRY, batch)["outcome"] == "processed"
    _host_message(client, did, MessageType.LOG, {"level": "warning", "message": "hot"})

    samples = client.get(f"/devices/{did}/telemetry?limit=1", headers=_as("alice")).json()
    assert samples == [
        {"ts": "2026-11-14T20:00:01Z", "readings": {"temperature_c": 41.0, "button": False}}
    ]
    [log] = client.get(f"/devices/{did}/logs", headers=_as("alice")).json()
    assert (log["kind"], log["level"], log["message"]) == ("log", "warning", "hot")
    assert client.get(f"/devices/{did}", headers=_as("alice")).json()["connection_status"] == (
        "online"
    )


def test_invalid_host_messages_are_rejected_not_stored(client: TestClient) -> None:
    _, did = _device(client)
    response = client.post(
        "/local/device-messages",
        json={"topic": f"devices/{did}/telemetry", "payload": {"nope": 1}},
    )
    assert response.json()["outcome"] == "rejected"
    assert client.get(f"/devices/{did}/telemetry", headers=_as("alice")).json() == []


def test_dashboard_reads_are_members_only(client: TestClient) -> None:
    _, did = _device(client)
    for path in ("telemetry", "logs", "channel"):
        assert client.get(f"/devices/{did}/{path}", headers=_as("mallory")).status_code == 404
    assert client.get(f"/devices/{did}/telemetry?limit=0", headers=_as("alice")).status_code == 422


def test_device_channel_is_appsync_safe(client: TestClient) -> None:
    pid, did = _device(client)
    channel = client.get(f"/devices/{did}/channel", headers=_as("alice")).json()
    assert channel["channel"] == "projects/{}/devices/{}".format(
        pid.replace("_", "-"), did.replace("_", "-")
    )
    assert set(channel["event_types"]) == {
        "device.telemetry",
        "device.log",
        "device.command.updated",
    }


def test_ping_round_trip_through_the_local_bridge(client: TestClient) -> None:
    pid, did = _device(client)
    command = client.post(
        f"/projects/{pid}/devices/{did}/commands", json={"name": "ping"}, headers=_as("alice")
    ).json()

    [outgoing] = client.post(f"/local/devices/{did}/commands/next").json()
    assert outgoing["topic"] == f"devices/{did}/commands"
    assert outgoing["payload"]["payload"]["command_id"] == command["id"]
    assert client.post(f"/local/devices/{did}/commands/next").json() == []  # taken once
    assert client.get(f"/commands/{command['id']}", headers=_as("alice")).json()["status"] == (
        "sent"
    )

    result = {"command_id": command["id"], "status": "succeeded", "output": {"pong": True}}
    _host_message(client, did, MessageType.COMMAND_RESULT, result)
    done = client.get(f"/commands/{command['id']}", headers=_as("alice")).json()
    assert (done["status"], done["output"]) == ("succeeded", {"pong": True})

    hub = client.app.state.container.local.realtime  # type: ignore[attr-defined]
    statuses = [e.data["status"] for e in hub.published if e.type == "device.command.updated"]
    assert statuses == ["sent", "succeeded"]


def test_commands_are_only_handed_to_their_own_device(client: TestClient) -> None:
    pid, did = _device(client)
    other = client.post(
        f"/projects/{pid}/devices", json={"display_name": "Other"}, headers=_as("alice")
    ).json()["id"]
    client.post(
        f"/projects/{pid}/devices/{did}/commands", json={"name": "ping"}, headers=_as("alice")
    )
    assert client.post(f"/local/devices/{other}/commands/next").json() == []
    assert len(client.post(f"/local/devices/{did}/commands/next").json()) == 1


def test_realtime_stream_checks_the_channel_and_membership(client: TestClient) -> None:
    pid, did = _device(client)
    seg = did.replace("_", "-")
    project = pid.replace("_", "-")
    url = "/local/realtime?channel="
    assert client.get(url + "elsewhere/x", headers=_as("alice")).status_code == 400
    assert client.get(url + f"projects/{project}/devices/{seg}").status_code == 401
    assert (
        client.get(url + f"projects/{project}/devices/{seg}", headers=_as("mallory")).status_code
        == 404
    )
    other_pid, _ = _device(client)
    wrong = f"projects/{other_pid.replace('_', '-')}/devices/{seg}"
    assert client.get(url + wrong, headers=_as("alice")).status_code == 404


def test_local_routes_stay_out_of_the_api_contract(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if p.startswith("/local")]
    assert "/devices/{device_id}/telemetry" in paths
