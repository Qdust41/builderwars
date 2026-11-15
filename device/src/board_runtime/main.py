"""Host runtime main loop (runs on the PC wired to the FREE-WILi, CPython 3.10+).

    DEVICE_ID=dev-local-001 uv run python -m board_runtime.main --samples 12

With ``DEVICE_TRANSPORT=stdout`` (default) messages are printed as JSON lines. With
``DEVICE_TRANSPORT=local-api`` they go to a local API (``LOCAL_API_URL``), which also delivers
commands back, so the web dashboard shows live telemetry without AWS. With
``DEVICE_TRANSPORT=cloud`` they go to the Builderwars API as the user signed in with
``builderwars login`` (``board_runtime.cloud``), and the dashboard shows them live.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from board_runtime.batching import TelemetryBatcher
from board_runtime.commands import CommandDispatcher
from board_runtime.config import (
    ConfigError,
    DeviceConfig,
    SensorKind,
    TransportKind,
    default_state_dir,
)
from board_runtime.connectivity import (
    BoundedMemoryBuffer,
    LocalApiTransport,
    OfflineBuffer,
    StdoutTransport,
    Transport,
    TransportError,
)
from board_runtime.connectivity.mqtt_client import MqttTransport
from board_runtime.hardware import (
    BoardUnavailableError,
    FreeWiliNotInstalledError,
    FreeWiliSensors,
    SensorReader,
    SimulatedSensors,
)
from board_runtime.logging import CsvLogSink, DeviceLogForwarder
from board_runtime.messages import MessageFactory
from board_runtime.sequence import FileSequenceStore, SequenceStore
from device_protocol import MessageType, MessageValidationError, decode_message, topic_for
from device_protocol.compat import UTC
from device_protocol.schemas import CommandPayload, DeviceState, EventSeverity
from device_protocol.topics import TopicChannel

log = logging.getLogger(__name__)
# Application events worth showing in the cloud log stream. ``main`` forwards this logger (not
# the transport's) to the cloud, so a send failure can never log its way into a loop.
app_log = logging.getLogger("board_runtime.app")


class BoardRuntime:
    def __init__(
        self,
        config: DeviceConfig,
        transport: Transport,
        sensors: SensorReader,
        *,
        buffer: OfflineBuffer | None = None,
        dispatcher: CommandDispatcher | None = None,
        sequence: SequenceStore | None = None,
        csv_sink: CsvLogSink | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.transport = transport
        self.sensors = sensors
        self.buffer = buffer or BoundedMemoryBuffer(config.offline_buffer_size)
        self.dispatcher = dispatcher or default_dispatcher(self)
        self.messages = MessageFactory(config, sequence)
        self.csv_sink = csv_sink
        self.batcher = TelemetryBatcher(
            window_s=config.batch_window_s, max_samples=config.batch_max_samples
        )
        self.board_available = True
        self._clock = clock
        self._started = clock()
        # Transport callbacks (incoming commands) may arrive on another thread.
        self._lock = threading.RLock()

    # -- lifecycle -------------------------------------------------------------------------
    def start(self) -> None:
        self.transport.connect()
        self.transport.subscribe(
            topic_for(self.config.device_id, TopicChannel.COMMANDS), self._on_command
        )
        self.send(MessageType.STATUS, {"state": DeviceState.ONLINE.value, "uptime_s": 0})

    def stop(self) -> None:
        self.flush_telemetry()
        self.send(MessageType.STATUS, {"state": DeviceState.SHUTTING_DOWN.value})
        self.transport.disconnect()
        if self.csv_sink is not None:
            self.csv_sink.close()

    # -- outbound --------------------------------------------------------------------------
    def send(self, message_type: MessageType, payload: dict[str, Any]) -> None:
        with self._lock:
            topic, body, envelope = self.messages.build(message_type, payload)
            if self.csv_sink is not None:
                self.csv_sink.write_envelope(envelope)
            dropped_before = getattr(self.buffer, "dropped", 0)
            self.buffer.append(topic, body)
            if getattr(self.buffer, "dropped", 0) > dropped_before:
                log.warning("offline buffer full; dropped the oldest message")
            self.flush()

    def flush(self) -> None:
        """Drain buffered messages in order; stop at the first failure and keep the rest."""
        with self._lock:
            while (item := self.buffer.peek()) is not None:
                try:
                    self.transport.publish(*item)
                except TransportError:
                    return
                self.buffer.pop()

    def sample(self) -> None:
        """Take one sensor sample; publish a telemetry batch when it is full or due."""
        now = self._clock()
        try:
            readings = self.sensors.read()
        except BoardUnavailableError as exc:
            was_available = self.board_available
            self._set_board_available(False, str(exc))
            if exc.hint and was_available:
                log.warning("hint: %s", exc.hint)
        else:
            self._set_board_available(True)
            # Configured sensors poll at their own rates, so some ticks have nothing due.
            batch = self.batcher.add(readings, at=datetime.now(UTC), now=now) if readings else None
            if batch is not None:
                self.send(MessageType.TELEMETRY, batch)
        if self.batcher.due(now):
            self.flush_telemetry()
        self.flush()  # retry anything buffered while offline

    def flush_telemetry(self) -> None:
        batch = self.batcher.flush()
        if batch is not None:
            self.send(MessageType.TELEMETRY, batch)

    def heartbeat(self) -> None:
        self.send(MessageType.HEARTBEAT, {"uptime_s": self.uptime_s})

    def send_log(self, payload: dict[str, Any]) -> None:
        self.send(MessageType.LOG, payload)

    def send_event(self, name: str, severity: EventSeverity, detail: str | None = None) -> None:
        self.send(MessageType.EVENT, {"name": name, "severity": severity.value, "detail": detail})

    @property
    def uptime_s(self) -> int:
        return int(self._clock() - self._started)

    def _set_board_available(self, available: bool, detail: str | None = None) -> None:
        if available == self.board_available:
            return
        self.board_available = available
        if available:
            log.info("board reconnected")
            self.send_event("board_reconnected", EventSeverity.INFO)
            self.send(MessageType.STATUS, {"state": DeviceState.ONLINE.value})
        else:
            log.warning("board unavailable: %s", detail)
            self.send_event("board_disconnected", EventSeverity.WARNING, detail)
            self.send(
                MessageType.STATUS,
                {"state": DeviceState.DEGRADED.value, "detail": "board unreachable over USB"},
            )

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
        app_log.info("command %s: %s", decoded.payload.name, result.status.value)


def default_dispatcher(runtime: BoardRuntime) -> CommandDispatcher:
    dispatcher = CommandDispatcher()
    dispatcher.register("ping", lambda _args: {"pong": True})
    dispatcher.register("get_uptime", lambda _args: {"uptime_s": runtime.uptime_s})
    # TODO (spec 07): board commands via the FREE-WILi adapter, e.g. set_io / set_board_leds.
    return dispatcher


def build_transport(config: DeviceConfig) -> Transport:
    if config.transport is TransportKind.MQTT:
        return MqttTransport(config)
    if config.transport is TransportKind.LOCAL_API:
        return LocalApiTransport(config.local_api_url, config.device_id)
    if config.transport is TransportKind.CLOUD:
        from board_runtime.cloud import AccountError, CloudApiTransport, CloudSession

        try:
            session = CloudSession.load(config.state_dir or default_state_dir())
        except AccountError as exc:
            raise TransportError(f"{exc} ({exc.hint})" if exc.hint else str(exc)) from exc
        return CloudApiTransport(session, config.device_id)
    return StdoutTransport()


def build_sensors(config: DeviceConfig) -> SensorReader:
    if config.sensors is SensorKind.FREEWILI:
        return FreeWiliSensors(port=config.serial_port)
    return SimulatedSensors()


def run_loop(
    config: DeviceConfig,
    *,
    samples: int | None = None,
    sensors: SensorReader | None = None,
    transport: Transport | None = None,
) -> None:
    """Run the sample/heartbeat loop until ``samples`` are taken or Ctrl+C."""
    sequence = FileSequenceStore(config.state_dir, config.device_id) if config.state_dir else None
    csv_sink = CsvLogSink(config.log_csv_path) if config.log_csv_path is not None else None
    if csv_sink is not None:
        log.info("logging device logs to %s", csv_sink.path)
    runtime = BoardRuntime(
        config,
        transport or build_transport(config),
        sensors or build_sensors(config),
        sequence=sequence,
        csv_sink=csv_sink,
    )
    forwarder = DeviceLogForwarder(runtime.send_log)
    app_log.addHandler(forwarder)
    app_log.setLevel(logging.INFO)
    runtime.start()
    app_log.info("host runtime started (sensors=%s)", config.sensors.value)
    count = 0
    last_heartbeat = time.monotonic()
    try:
        while samples is None or count < samples:
            runtime.sample()
            count += 1
            if time.monotonic() - last_heartbeat >= config.heartbeat_interval_s:
                runtime.heartbeat()
                last_heartbeat = time.monotonic()
            if samples is None or count < samples:
                time.sleep(config.sample_interval_s)
    except KeyboardInterrupt:
        pass
    finally:
        app_log.info("host runtime stopping")
        runtime.stop()
        app_log.removeHandler(forwarder)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the host runtime loop (config from DEVICE_* / IOT_* env vars)"
    )
    parser.add_argument("--samples", type=int, default=None, help="stop after N samples")
    parser.add_argument("--port", help="FREE-WILi serial port, e.g. /dev/ttyACM0 (= DEVICE_PORT)")
    parser.add_argument("--device-id", help="device id (= DEVICE_ID)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    env = dict(os.environ)
    if args.port:
        env["DEVICE_PORT"] = args.port
    if args.device_id:
        env["DEVICE_ID"] = args.device_id
    try:
        config = DeviceConfig.from_env(env)
        run_loop(config, samples=args.samples)
    except (ConfigError, FreeWiliNotInstalledError, TransportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
