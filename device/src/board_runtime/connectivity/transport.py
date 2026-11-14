from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, TextIO

MessageHandler = Callable[[str, bytes], None]


class TransportError(Exception):
    """Raised when a publish cannot be delivered (caller should buffer and retry)."""


class Transport(Protocol):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def publish(self, topic: str, payload: bytes) -> None: ...
    def subscribe(self, topic: str, handler: MessageHandler) -> None: ...
    @property
    def connected(self) -> bool: ...


class StdoutTransport:
    """Local development transport: writes one JSON line per message ``{"topic", "payload"}``.

    The output can be piped into the local worker harness. It does NOT authenticate as an AWS
    IoT device and must not be described as doing so.
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stdout
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def publish(self, topic: str, payload: bytes) -> None:
        if not self._connected:
            raise TransportError("not connected")
        line = json.dumps({"topic": topic, "payload": json.loads(payload)})
        self._stream.write(line + "\n")
        self._stream.flush()

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        # No inbound path locally; commands can be injected in tests via RecordingTransport.
        pass


@dataclass
class RecordingTransport:
    """In-memory transport for tests. Set ``fail_publishes`` to simulate an outage."""

    published: list[tuple[str, bytes]] = field(default_factory=list)
    handlers: dict[str, MessageHandler] = field(default_factory=dict)
    fail_publishes: bool = False
    _connected: bool = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def publish(self, topic: str, payload: bytes) -> None:
        if self.fail_publishes or not self._connected:
            raise TransportError("simulated outage")
        self.published.append((topic, payload))

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        self.handlers[topic] = handler

    def deliver(self, topic: str, payload: bytes) -> None:
        self.handlers[topic](topic, payload)
