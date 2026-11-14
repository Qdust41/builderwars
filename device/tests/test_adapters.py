"""FREE-WILi and MQTT adapters against fakes (no hardware, no AWS)."""

from __future__ import annotations

from enum import Enum

import pytest

from board_runtime.config import DeviceConfig, TransportKind
from board_runtime.connectivity import TransportError
from board_runtime.connectivity.mqtt_client import MqttTransport
from board_runtime.hardware import BoardUnavailableError, FreeWiliSensors


class _Ok:
    def __init__(self, value):
        self._value = value

    def is_err(self) -> bool:
        return False

    def unwrap(self):
        return self._value


class _Err:
    def is_err(self) -> bool:
        return True

    def unwrap_err(self) -> str:
        return "serial timeout"


class Button(Enum):
    Red = 1
    Green = 2


class FakeFreeWili:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, object]] = []

    def get_io(self, processor):
        self.calls.append(("get_io", processor))
        return _Err() if self.fail else _Ok((0, 1, 1))

    def read_all_buttons(self, processor):
        self.calls.append(("read_all_buttons", processor))
        return _Ok({Button.Red: True, Button.Green: False})


def test_freewili_readings_are_flat_scalars() -> None:
    device = FakeFreeWili()
    readings = FreeWiliSensors(device).read()
    assert readings == {
        "io_0": 0,
        "io_1": 1,
        "io_2": 1,
        "button_red": True,
        "button_green": False,
    }
    assert device.calls == [("get_io", "Main"), ("read_all_buttons", "Display")]


def test_freewili_errors_become_board_unavailable() -> None:
    with pytest.raises(BoardUnavailableError):
        FreeWiliSensors(FakeFreeWili(fail=True)).read()


class _Future:
    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc

    def result(self, timeout=None):
        if self._exc:
            raise self._exc


class FakeConnection:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.published: list[tuple[str, bytes]] = []
        self.subscriptions: dict = {}
        self.fail_publish = False

    def connect(self):
        return _Future()

    def disconnect(self):
        return _Future()

    def publish(self, topic, payload, qos):
        if self.fail_publish:
            return _Future(TimeoutError()), 1
        self.published.append((topic, payload))
        return _Future(), 1

    def subscribe(self, topic, qos, callback):
        self.subscriptions[topic] = callback
        return _Future(), 2


def _mqtt_config() -> DeviceConfig:
    return DeviceConfig(
        device_id="dev-1",
        hardware_model="freewili-1-og",
        firmware_version="1.0",
        transport=TransportKind.MQTT,
        mqtt_endpoint="example-ats.iot.us-east-1.amazonaws.com",
        cert_path="/certs/dev.pem",
        key_path="/certs/dev.key",
        ca_path="/certs/ca.pem",
    )


def test_mqtt_uses_thing_name_as_client_id_and_forwards_messages() -> None:
    holder: dict[str, FakeConnection] = {}

    def factory(**kwargs):
        holder["c"] = FakeConnection(**kwargs)
        return holder["c"]

    transport = MqttTransport(_mqtt_config(), connection_factory=factory)
    transport.connect()
    conn = holder["c"]
    assert conn.kwargs["client_id"] == "dev-1"
    assert conn.kwargs["cert_filepath"] == "/certs/dev.pem"

    transport.publish("devices/dev-1/telemetry", b"{}")
    assert conn.published == [("devices/dev-1/telemetry", b"{}")]

    received: list[tuple[str, bytes]] = []
    transport.subscribe("devices/dev-1/commands", lambda t, p: received.append((t, p)))
    conn.subscriptions["devices/dev-1/commands"](
        topic="devices/dev-1/commands", payload=b"x", dup=False, qos=1, retain=False
    )
    assert received == [("devices/dev-1/commands", b"x")]


def test_mqtt_publish_failures_and_interruptions_raise_transport_error() -> None:
    holder: dict[str, FakeConnection] = {}

    def factory(**kwargs):
        holder["c"] = FakeConnection(**kwargs)
        return holder["c"]

    transport = MqttTransport(_mqtt_config(), connection_factory=factory)
    transport.connect()
    holder["c"].fail_publish = True
    with pytest.raises(TransportError):
        transport.publish("devices/dev-1/telemetry", b"{}")

    holder["c"].kwargs["on_connection_interrupted"](connection=None, error=OSError())
    assert not transport.connected
    with pytest.raises(TransportError, match="not connected"):
        transport.publish("devices/dev-1/telemetry", b"{}")
    holder["c"].kwargs["on_connection_resumed"](
        connection=None, return_code=0, session_present=True
    )
    assert transport.connected
