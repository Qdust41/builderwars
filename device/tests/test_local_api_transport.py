"""LocalApiTransport against a stub HTTP server (stands in for the local API's /local routes)."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from board_runtime.config import DeviceConfig, TransportKind
from board_runtime.connectivity import LocalApiTransport, TransportError
from board_runtime.hardware import SimulatedSensors
from board_runtime.main import BoardRuntime, build_transport
from device_protocol import DeviceEnvelope, MessageType, decode_message, encode_message


class _Stub:
    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.pending: list[dict[str, Any]] = []


@pytest.fixture
def stub() -> Iterator[tuple[_Stub, str]]:
    state = _Stub()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"null")
            if self.path == "/local/device-messages":
                state.received.append(body)
                reply: Any = {"outcome": "processed"}
            elif self.path.endswith("/commands/next"):
                reply, state.pending = state.pending, []
            else:
                self.send_response(404)
                self.end_headers()
                return
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def _config(url: str) -> DeviceConfig:
    return DeviceConfig(
        device_id="dev_local1",
        hardware_model="simulated-board",
        firmware_version="0.0.0-test",
        transport=TransportKind.LOCAL_API,
        local_api_url=url,
    )


def test_config_selects_the_local_api_transport() -> None:
    cfg = DeviceConfig.from_env(
        {"DEVICE_ID": "dev_x", "DEVICE_TRANSPORT": "local-api", "LOCAL_API_URL": "http://h:1"}
    )
    transport = build_transport(cfg)
    assert isinstance(transport, LocalApiTransport)


def test_runtime_publishes_through_the_api_and_answers_a_ping(stub) -> None:
    state, url = stub
    transport = LocalApiTransport(url, "dev_local1", poll_interval_s=3600)  # poll by hand
    runtime = BoardRuntime(_config(url), transport, SimulatedSensors(seed=1))
    runtime.start()
    assert state.received[0]["topic"] == "devices/dev_local1/status"

    command = DeviceEnvelope.new(
        device_id="dev_local1",
        message_type=MessageType.COMMAND,
        payload={"command_id": "6f1c1d5e-7d3a-4a52-9a8e-2b8e3f1f6a10", "name": "ping", "args": {}},
    )
    state.pending = [
        {"topic": "devices/dev_local1/commands", "payload": json.loads(encode_message(command))}
    ]
    assert transport.poll_commands() == 1
    result = decode_message(json.dumps(state.received[-1]["payload"]).encode())
    assert result.envelope.message_type is MessageType.COMMAND_RESULT
    assert result.payload.output == {"pong": True}
    runtime.stop()


def test_unreachable_api_raises_transport_error_so_messages_are_buffered() -> None:
    transport = LocalApiTransport("http://127.0.0.1:9", "dev_local1", poll_interval_s=3600)
    transport.connect()
    try:
        with pytest.raises(TransportError):
            transport.publish("devices/dev_local1/heartbeat", b'{"x": 1}')
    finally:
        transport.disconnect()
