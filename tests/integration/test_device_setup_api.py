"""Test setup (laptop -> FREE-WILi -> up to 4 target boards) and sensors over the API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.settings import AppEnv, Settings
from board_runtime.cloud import (
    CloudApiTransport,
    CloudSession,
    bridge_report,
    fetch_sensors,
    host_report,
    login,
    report_connection,
)
from board_runtime.config import DeviceConfig, TransportKind
from board_runtime.hardware import BoardInfo, ConfiguredSensors, FreeWiliSensors
from board_runtime.main import BoardRuntime

pytestmark = pytest.mark.integration

TMP102 = {
    "key": "board_temp_c",
    "name": "Board temperature",
    "unit": "°C",
    "poll_interval_s": 2,
    "bus": {"protocol": "i2c", "address": 0x48, "reg": 0, "length": 2},
    "decode": {"data_type": "i16_be", "bit_shift": 4, "scale": 0.0625},
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings(app_env=AppEnv.TEST)))


def _as(user: str) -> dict[str, str]:
    return {"X-Dev-User": user}


def _device(client: TestClient) -> tuple[str, str]:
    pid = client.post("/projects", json={"name": "Rover"}, headers=_as("alice")).json()["id"]
    did = client.post(
        f"/projects/{pid}/devices", json={"display_name": "Bench"}, headers=_as("alice")
    ).json()["id"]
    return pid, did


def _board(client: TestClient, did: str, name: str = "Motor controller") -> str:
    response = client.post(f"/devices/{did}/boards", json={"name": name}, headers=_as("alice"))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _sensor(board_id: str, **change: object) -> dict:
    return {**TMP102, "board_id": board_id, **change}


def _add_member(client: TestClient, pid: str, user: str) -> None:
    client.get("/projects", headers=_as(user))  # registers the dev user
    added = client.post(
        f"/projects/{pid}/members", json={"email": f"{user}@example.com"}, headers=_as("alice")
    )
    assert added.status_code == 201, added.text


def test_empty_setup_until_the_cli_reports(client: TestClient) -> None:
    _, did = _device(client)
    setup = client.get(f"/devices/{did}/setup", headers=_as("alice")).json()
    assert setup["host"] is None
    assert setup["bridge"] is None
    assert setup["boards"] == []
    assert setup["sensors"] == []
    assert setup["max_boards"] == 4


def test_cli_reports_laptop_and_freewili(client: TestClient) -> None:
    pid, did = _device(client)
    _add_member(client, pid, "bob")  # a plain member running the CLI may report
    report = {
        "host": {
            "hostname": "bench-laptop",
            "os": "Linux 6.8 (x86_64)",
            "python_version": "3.10.14",
            "cli_version": "0.1.0",
            "future_field": "ignored",
        },
        "bridge": {"serial": "FW4521", "main_port": "/dev/ttyACM0", "library_version": "0.0.51"},
    }
    put = client.put(f"/devices/{did}/setup/connection", json=report, headers=_as("bob"))
    assert put.status_code == 200, put.text
    setup = client.get(f"/devices/{did}/setup", headers=_as("alice")).json()
    assert setup["host"]["hostname"] == "bench-laptop"
    assert setup["bridge"]["serial"] == "FW4521"
    assert setup["bridge"]["model"] == "FREE-WILi"
    assert setup["reported_at"] is not None


def test_target_boards_and_sensor_crud(client: TestClient) -> None:
    _, did = _device(client)
    created_board = client.post(
        f"/devices/{did}/boards",
        json={"name": "Motor controller rev B", "notes": "TMP102 on I2C0"},
        headers=_as("alice"),
    )
    assert created_board.status_code == 201, created_board.text
    board = created_board.json()["id"]
    renamed = client.put(
        f"/devices/{did}/boards/{board}", json={"name": "Motor ctrl C"}, headers=_as("alice")
    )
    assert renamed.json()["name"] == "Motor ctrl C"

    created = client.post(f"/devices/{did}/sensors", json=_sensor(board), headers=_as("alice"))
    assert created.status_code == 201, created.text
    sensor = created.json()
    assert sensor["protocol"] == "i2c"
    assert sensor["board_id"] == board
    assert sensor["bus"]["setup_writes"] == []
    assert sensor["decode"]["scale"] == 0.0625

    # Keys are unique per device, across boards: they share one telemetry stream.
    other = _board(client, did, "Power board")
    dup = client.post(f"/devices/{did}/sensors", json=_sensor(other), headers=_as("alice"))
    assert dup.status_code == 409

    moved = client.put(
        f"/devices/{did}/sensors/{sensor['id']}",
        json=_sensor(other, poll_interval_s=5, enabled=False),
        headers=_as("alice"),
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["enabled"] is False
    assert moved.json()["board_id"] == other

    setup = client.get(f"/devices/{did}/setup", headers=_as("alice")).json()
    assert [b["name"] for b in setup["boards"]] == ["Motor ctrl C", "Power board"]
    assert setup["sensors"][0]["poll_interval_s"] == 5

    # Deleting a board deletes its sensors.
    assert client.delete(f"/devices/{did}/boards/{other}", headers=_as("alice")).status_code == 204
    assert client.get(f"/devices/{did}/sensors", headers=_as("alice")).json() == []


def test_at_most_four_boards(client: TestClient) -> None:
    _, did = _device(client)
    for n in range(4):
        _board(client, did, f"Board {n}")
    fifth = client.post(f"/devices/{did}/boards", json={"name": "Five"}, headers=_as("alice"))
    assert fifth.status_code == 409
    assert "at most 4" in fifth.text


def test_sensor_needs_a_board_of_this_device(client: TestClient) -> None:
    _, did = _device(client)
    _, other = _device(client)
    foreign = _board(client, other)
    response = client.post(f"/devices/{did}/sensors", json=_sensor(foreign), headers=_as("alice"))
    assert response.status_code == 404
    missing = client.post(f"/devices/{did}/sensors", json=TMP102, headers=_as("alice"))
    assert missing.status_code == 422


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"key": "Board Temp"}, "key"),
        ({"bus": {"protocol": "can", "id": 1}}, "protocol"),
        ({"bus": {"protocol": "i2c", "address": 200, "reg": 0}}, "address"),
        ({"decode": {"data_type": "u32_be"}}, "needs 4 bytes"),
        ({"bus": {"protocol": "spi", "write": [0x80], "read_offset": 1}}, "read_offset"),
        ({"bus": {"protocol": "uart", "response_pattern": "(unclosed"}}, "regular expression"),
        ({"surprise": True}, "surprise"),
    ],
)
def test_invalid_sensors_are_rejected(client: TestClient, change: dict, fragment: str) -> None:
    _, did = _device(client)
    board = _board(client, did)
    response = client.post(
        f"/devices/{did}/sensors", json=_sensor(board, **change), headers=_as("alice")
    )
    assert response.status_code == 422
    assert fragment in response.text


def test_only_the_owner_configures(client: TestClient) -> None:
    pid, did = _device(client)
    _add_member(client, pid, "bob")
    board = _board(client, did)
    assert client.get(f"/devices/{did}/setup", headers=_as("bob")).status_code == 200
    assert (
        client.post(f"/devices/{did}/sensors", json=_sensor(board), headers=_as("bob")).status_code
        == 403
    )
    assert (
        client.post(f"/devices/{did}/boards", json={"name": "x"}, headers=_as("bob")).status_code
        == 403
    )
    # Outsiders can't even tell the device exists.
    assert client.get(f"/devices/{did}/setup", headers=_as("mallory")).status_code == 404
    assert client.get(f"/devices/{did}/sensors", headers=_as("mallory")).status_code == 404


def test_sensor_of_another_device_is_not_found(client: TestClient) -> None:
    _, did = _device(client)
    _, other = _device(client)
    board = _board(client, did)
    sensor = client.post(
        f"/devices/{did}/sensors", json=_sensor(board), headers=_as("alice")
    ).json()
    assert (
        client.delete(f"/devices/{other}/sensors/{sensor['id']}", headers=_as("alice")).status_code
        == 404
    )


# -- the CLI side: pull sensors, read them on a (fake) FREE-WILi, upload ----------------------
def test_cli_reads_the_defined_sensors_and_reports_the_chain(
    client: TestClient, tmp_path: Path
) -> None:
    _, did = _device(client)
    board = _board(client, did)
    client.post(f"/devices/{did}/sensors", json=_sensor(board), headers=_as("alice"))
    client.post(
        f"/devices/{did}/sensors",
        json=_sensor(board, key="later", enabled=False),
        headers=_as("alice"),
    )

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
    listed = fetch_sensors(session, did)
    assert [s.key for s in listed.sensors] == ["board_temp_c", "later"]
    assert listed.boards["board_temp_c"] == "Motor controller"

    info = BoardInfo("FREE-WILi", "FW4521", "FreeWili", "/dev/ttyACM0", "/dev/ttyACM1")
    report_connection(
        session,
        did,
        host_report(cli_version="0.1.0", sensor_source="freewili"),
        bridge_report(info, library_version="0.0.51"),
    )
    setup = client.get(f"/devices/{did}/setup", headers=_as("alice")).json()
    assert setup["bridge"]["serial"] == "FW4521"
    assert setup["host"]["sensor_source"] == "freewili"

    class Tmp102:  # answers 25 °C at 0x48 register 0
        def read_i2c(self, address, reg, size, processor):  # type: ignore[no-untyped-def]
            assert (address, reg, size) == (0x48, 0, 2)
            return _Ok(bytes([0x19, 0x00]))

    reader = ConfiguredSensors(listed.sensors, FreeWiliSensors(Tmp102()))
    config = DeviceConfig(
        device_id=did,
        hardware_model="freewili",
        firmware_version="1.0.0",
        transport=TransportKind.CLOUD,
        batch_max_samples=1,
    )
    runtime = BoardRuntime(config, CloudApiTransport(session, did), reader)
    runtime.start()
    runtime.sample()
    runtime.stop()

    samples = client.get(f"/devices/{did}/telemetry", headers=_as("alice")).json()
    assert samples[-1]["readings"] == {"board_temp_c": 25.0}


class _Ok:
    def __init__(self, value: object) -> None:
        self._value = value

    def is_err(self) -> bool:
        return False

    def unwrap(self) -> object:
        return self._value


def _send_via(client: TestClient):  # type: ignore[no-untyped-def]
    def send(method: str, url: str, headers: dict, body: bytes | None, timeout: float):  # type: ignore[no-untyped-def]
        path = url.removeprefix("http://localhost:8000")
        response = client.request(method, path, headers=headers, content=body)
        return response.status_code, response.content

    return send


# -- one run at a time: `builderwars run` locks the board -----------------------------------
def _report(run_id: str, host: str = "bench-laptop", **extra: object) -> dict:
    return {
        "host": {"hostname": host, "os": "Linux", "python_version": "3.10", "cli_version": "0.1"},
        "run_id": run_id,
        **extra,
    }


def _upload(client: TestClient, did: str, run_id: str | None, user: str = "alice"):  # type: ignore[no-untyped-def]
    envelope = {
        "message_id": f"m-{run_id}-{user}",
        "device_id": did,
        "message_type": "heartbeat",
        "schema_version": 1,
        "sequence": 1,
        "timestamp": "2026-11-15T12:00:00Z",
        "payload": {"uptime_s": 1},
    }
    body: dict = {
        "messages": [{"topic": f"builderwars/devices/{did}/heartbeat", "payload": envelope}]
    }
    if run_id:
        body["run_id"] = run_id
    return client.post(f"/devices/{did}/messages", json=body, headers=_as(user))


def test_a_run_locks_the_board_until_it_stops(client: TestClient) -> None:
    pid, did = _device(client)
    _add_member(client, pid, "bob")
    url = f"/devices/{did}/setup/connection"
    first = client.put(url, json=_report("run_aaaaaaaa"), headers=_as("alice"))
    assert first.status_code == 200, first.text
    run = first.json()["run"]
    assert run["hostname"] == "bench-laptop"
    assert run["user_id"]

    # The same run may report again; another run is refused while the first one holds it.
    assert client.put(url, json=_report("run_aaaaaaaa"), headers=_as("alice")).status_code == 200
    second = client.put(url, json=_report("run_bbbbbbbb", "bob-laptop"), headers=_as("bob"))
    assert second.status_code == 409
    assert second.json()["code"] == "board_in_use"
    assert "alice@example.com's run on bench-laptop" in second.json()["detail"]

    # Stopping frees it for the next run (a wrong run id releases nothing).
    assert (
        client.delete(f"/devices/{did}/setup/run/run_zzzzzzzz", headers=_as("bob")).status_code
        == 204
    )
    assert client.put(url, json=_report("run_bbbbbbbb"), headers=_as("bob")).status_code == 409
    assert (
        client.delete(f"/devices/{did}/setup/run/run_aaaaaaaa", headers=_as("alice")).status_code
        == 204
    )
    assert client.get(f"/devices/{did}/setup", headers=_as("alice")).json()["run"] is None
    assert client.put(url, json=_report("run_bbbbbbbb"), headers=_as("bob")).status_code == 200


def test_take_over_stops_the_old_run(client: TestClient) -> None:
    _, did = _device(client)
    url = f"/devices/{did}/setup/connection"
    client.put(url, json=_report("run_aaaaaaaa"), headers=_as("alice"))
    assert _upload(client, did, "run_aaaaaaaa").status_code == 200
    took = client.put(url, json=_report("run_bbbbbbbb", take_over=True), headers=_as("alice"))
    assert took.status_code == 200, took.text
    old = _upload(client, did, "run_aaaaaaaa")
    assert old.status_code == 409
    assert old.json()["code"] == "run_superseded"
    # Saved data uploaded without a run (builderwars upload) is never blocked by the lock.
    assert _upload(client, did, None).status_code == 200


def test_lock_lapses_when_the_run_goes_quiet() -> None:
    from datetime import UTC, datetime, timedelta

    from domain.devices import BoardInUseError, DeviceSetup

    t0 = datetime(2026, 11, 15, 12, tzinfo=UTC)
    held = DeviceSetup(device_id="dev_1").claim_run("run_a", by="alice", at=t0)
    with pytest.raises(BoardInUseError):
        held.claim_run("run_b", by="bob", at=t0 + timedelta(seconds=74))
    later = held.claim_run("run_b", by="bob", at=t0 + timedelta(seconds=76))
    assert later.run_id == "run_b"
    assert later.release_run("run_a", at=t0).run_id == "run_b"


def test_cli_refuses_a_held_board_and_stops_when_taken_over(
    client: TestClient, tmp_path: Path
) -> None:
    from board_runtime.cloud import BoardInUseError

    _, did = _device(client)
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
    host = host_report(cli_version="0.1.0", sensor_source="simulated")
    report_connection(session, did, host, None, run_id="run_first000")
    with pytest.raises(BoardInUseError, match="in use"):
        report_connection(session, did, host, None, run_id="run_second00")

    config = DeviceConfig(
        device_id=did,
        hardware_model="freewili",
        firmware_version="1.0.0",
        transport=TransportKind.CLOUD,
        batch_max_samples=1,
        sample_interval_s=0.01,
        run_id="run_first000",
    )
    from board_runtime.hardware import SimulatedSensors
    from board_runtime.main import run_loop

    taken = False

    class TakeOverMidRun(SimulatedSensors):
        def read(self):  # type: ignore[no-untyped-def]
            nonlocal taken
            if not taken:
                taken = True
                report_connection(session, did, host, None, run_id="run_second00", take_over=True)
            return super().read()

    transport = CloudApiTransport(session, did, poll_interval_s=None, run_id="run_first000")
    reason = run_loop(config, samples=20, sensors=TakeOverMidRun(), transport=transport)
    assert reason is not None
    assert "taken over" in reason
