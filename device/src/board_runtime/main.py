"""Board runtime main loop.

    DEVICE_ID=dev-local-001 uv run python -m board_runtime.main --iterations 3

With ``DEVICE_TRANSPORT=stdout`` (default) messages are printed as JSON lines.
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable
from typing import Any

from board_runtime.commands import CommandDispatcher
from board_runtime.config import DeviceConfig, TransportKind
from board_runtime.connectivity import (
    BoundedMemoryBuffer,
    OfflineBuffer,
    StdoutTransport,
    Transport,
    TransportError,
)
from board_runtime.connectivity.mqtt_client import MqttTransport
from board_runtime.hardware import SensorReader, SimulatedSensors
from board_runtime.messages import MessageFactory
from device_protocol import MessageType, MessageValidationError, decode_message, topic_for
from device_protocol.schemas import CommandPayload, DeviceState
from device_protocol.topics import TopicChannel

log = logging.getLogger(__name__)


class BoardRuntime:
    def __init__(
        self,
        config: DeviceConfig,
        transport: Transport,
        sensors: SensorReader,
        *,
        buffer: OfflineBuffer | None = None,
        dispatcher: CommandDispatcher | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.transport = transport
        self.sensors = sensors
        self.buffer = buffer or BoundedMemoryBuffer(config.offline_buffer_size)
        self.dispatcher = dispatcher or default_dispatcher(self)
        self.messages = MessageFactory(config)
        self._clock = clock
        self._started = clock()

    # -- lifecycle -------------------------------------------------------------------------
    def start(self) -> None:
        # TODO: reconnect loop using BackoffPolicy once a real transport exists.
        self.transport.connect()
        self.transport.subscribe(
            topic_for(self.config.device_id, TopicChannel.COMMANDS), self._on_command
        )
        self.send(MessageType.STATUS, {"state": DeviceState.ONLINE.value, "uptime_s": 0})

    def stop(self) -> None:
        self.send(MessageType.STATUS, {"state": DeviceState.SHUTTING_DOWN.value})
        self.transport.disconnect()

    # -- outbound --------------------------------------------------------------------------
    def send(self, message_type: MessageType, payload: dict[str, Any]) -> None:
        topic, body = self.messages.build(message_type, payload)
        self.buffer.append(topic, body)
        self.flush()

    def flush(self) -> None:
        """Drain buffered messages in order; stop at the first failure and keep the rest."""
        while (item := self.buffer.peek()) is not None:
            try:
                self.transport.publish(*item)
            except TransportError:
                return
            self.buffer.pop()

    def tick(self) -> None:
        self.send(MessageType.TELEMETRY, self.sensors.read())

    def heartbeat(self) -> None:
        self.send(MessageType.HEARTBEAT, {"uptime_s": self.uptime_s})

    def send_log(self, payload: dict[str, Any]) -> None:
        self.send(MessageType.LOG, payload)

    @property
    def uptime_s(self) -> int:
        return int(self._clock() - self._started)

    # -- inbound ---------------------------------------------------------------------------
    def _on_command(self, topic: str, body: bytes) -> None:
        try:
            decoded = decode_message(body)
        except MessageValidationError as exc:
            log.warning("dropping invalid command: %s", exc.reason.value)
            return
        if decoded.envelope.message_type is not MessageType.COMMAND or not isinstance(
            decoded.payload, CommandPayload
        ):
            log.warning("ignoring non-command message on commands topic")
            return
        if decoded.envelope.device_id != self.config.device_id:
            log.warning("ignoring command addressed to another device")
            return
        result = self.dispatcher.dispatch(decoded.payload)
        self.send(MessageType.COMMAND_RESULT, result.model_dump(mode="json"))


def default_dispatcher(runtime: BoardRuntime) -> CommandDispatcher:
    dispatcher = CommandDispatcher()
    dispatcher.register("ping", lambda _args: {"pong": True})
    dispatcher.register("get_uptime", lambda _args: {"uptime_s": runtime.uptime_s})
    return dispatcher


def build_transport(config: DeviceConfig) -> Transport:
    if config.transport is TransportKind.MQTT:
        return MqttTransport(config)
    return StdoutTransport()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the board runtime loop")
    parser.add_argument("--iterations", type=int, default=None, help="stop after N telemetry ticks")
    args = parser.parse_args(argv)

    config = DeviceConfig.from_env()
    runtime = BoardRuntime(config, build_transport(config), SimulatedSensors())
    # TODO: replace SimulatedSensors with real drivers once the board is chosen.
    runtime.start()
    count = 0
    last_heartbeat = time.monotonic()
    try:
        while args.iterations is None or count < args.iterations:
            runtime.tick()
            count += 1
            if time.monotonic() - last_heartbeat >= config.heartbeat_interval_s:
                runtime.heartbeat()
                last_heartbeat = time.monotonic()
            if args.iterations is None or count < args.iterations:
                time.sleep(config.telemetry_interval_s)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.stop()


if __name__ == "__main__":
    main()
