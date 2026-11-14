from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.settings import AppEnv, Settings

pytestmark = pytest.mark.integration


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings(app_env=AppEnv.TEST)))


def _as(user: str) -> dict[str, str]:
    return {"X-Dev-User": user}


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "test"}


def test_requests_without_identity_are_unauthorised(client: TestClient) -> None:
    assert client.get("/projects").status_code == 401


def test_project_device_session_job_flow(client: TestClient) -> None:
    project = client.post("/projects", json={"name": "Rover"}, headers=_as("alice")).json()
    pid = project["id"]
    assert [p["id"] for p in client.get("/projects", headers=_as("alice")).json()] == [pid]

    device = client.post(
        f"/projects/{pid}/devices",
        json={"display_name": "Bench board", "hardware_model": "devboard-x"},
        headers=_as("alice"),
    )
    assert device.status_code == 201
    did = device.json()["id"]
    status = client.get(f"/devices/{did}/status", headers=_as("alice")).json()
    assert status["connection_status"] == "unknown"

    session = client.post(
        f"/projects/{pid}/sessions", json={"device_id": did}, headers=_as("alice")
    ).json()
    channel = client.get(f"/sessions/{session['id']}/channel", headers=_as("alice")).json()
    assert channel["channel"] == f"projects/{pid}/sessions/{session['id']}"

    job = client.post(f"/projects/{pid}/jobs", json={"job_type": "test_run"}, headers=_as("alice"))
    assert job.status_code == 202
    assert (
        client.get(f"/jobs/{job.json()['id']}", headers=_as("alice")).json()["status"] == "queued"
    )


def test_other_users_cannot_see_a_project_or_its_resources(client: TestClient) -> None:
    pid = client.post("/projects", json={"name": "Secret"}, headers=_as("alice")).json()["id"]
    did = client.post(
        f"/projects/{pid}/devices",
        json={"display_name": "b", "hardware_model": "m"},
        headers=_as("alice"),
    ).json()["id"]
    assert client.get(f"/projects/{pid}", headers=_as("mallory")).status_code == 404
    assert client.get(f"/devices/{did}", headers=_as("mallory")).status_code == 404
    assert (
        client.post(
            f"/projects/{pid}/jobs", json={"job_type": "ai_run"}, headers=_as("mallory")
        ).status_code
        == 404
    )
    assert client.get("/projects", headers=_as("mallory")).json() == []


def test_request_validation(client: TestClient) -> None:
    assert client.post("/projects", json={"name": ""}, headers=_as("a")).status_code == 422
    pid = client.post("/projects", json={"name": "P"}, headers=_as("a")).json()["id"]
    bad_job = client.post(f"/projects/{pid}/jobs", json={"job_type": "flash"}, headers=_as("a"))
    assert bad_job.status_code == 422


def test_device_command_flow(client: TestClient) -> None:
    pid = client.post("/projects", json={"name": "Bench"}, headers=_as("alice")).json()["id"]
    device = client.post(
        f"/projects/{pid}/devices", json={"display_name": "FREE-WILi #1"}, headers=_as("alice")
    ).json()
    assert device["hardware_model"] == "freewili-1-og"
    assert device["extensions"] == ["bottlenose-wifi-orca"]

    sent = client.post(
        f"/projects/{pid}/devices/{device['id']}/commands",
        json={"name": "ping", "args": {}},
        headers=_as("alice"),
    )
    assert sent.status_code == 202
    assert sent.json()["status"] == "queued"
    got = client.get(f"/commands/{sent.json()['id']}", headers=_as("alice"))
    assert got.json()["id"] == sent.json()["id"]

    assert client.get(f"/commands/{sent.json()['id']}", headers=_as("mallory")).status_code == 404
    bad = client.post(
        f"/projects/{pid}/devices/{device['id']}/commands",
        json={"name": "rm -rf /"},
        headers=_as("alice"),
    )
    assert bad.status_code == 422


def test_dev_header_users_can_be_added_by_email(client: TestClient) -> None:
    pid = client.post("/projects", json={"name": "Shared"}, headers=_as("alice")).json()["id"]
    client.get("/projects", headers=_as("bob"))  # dev mode registers bob@example.com on first use
    added = client.post(
        f"/projects/{pid}/members", json={"email": "bob@example.com"}, headers=_as("alice")
    )
    assert added.status_code == 201
    assert added.json()["role"] == "member"
    assert client.get(f"/projects/{pid}", headers=_as("bob")).status_code == 200
