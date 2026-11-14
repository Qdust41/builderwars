"""AWS IoT Core MQTT/TLS transport using the AWS IoT Device SDK v2 (``awsiotsdk``).

Install with the ``mqtt`` extra. Mutual TLS with the per-device X.509 certificate; the client
id MUST equal the IoT thing name because the IoT policy authorises
``client/${iot:Connection.Thing.ThingName}``. QoS 1 both ways; the cloud deduplicates.

The SDK reconnects on its own (with backoff) after an interruption; while disconnected,
``publish`` raises ``TransportError`` so the runtime keeps messages in its ``OfflineBuffer``
and replays them in order once the connection is back.
SDK callbacks (incoming commands, interruptions) run on SDK threads; ``BoardRuntime`` locks
around its buffer for that reason.

Not yet exercised against a real IoT endpoint (see docs/aws-deployment.md). Certificate
contents are never read or logged here, only their paths are passed to the SDK.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from board_runtime.config import DeviceConfig
from board_runtime.connectivity.transport import MessageHandler, TransportError

log = logging.getLogger(__name__)

ConnectionFactory = Callable[..., Any]
TIMEOUT_S = 10.0


def _sdk_connection_factory(**kwargs: Any) -> Any:
    try:
        from awsiot import mqtt_connection_builder
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("install the 'mqtt' extra: uv sync --extra mqtt") from exc
    return mqtt_connection_builder.mtls_from_path(**kwargs)


def _qos_at_least_once() -> Any:
    try:
        from awscrt import mqtt
    except ImportError:  # tests with a fake connection
        return 1
    return mqtt.QoS.AT_LEAST_ONCE


class MqttTransport:
    def __init__(
        self,
        config: DeviceConfig,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        config.validate()
        self._config = config
        self._factory = connection_factory or _sdk_connection_factory
        self._connection: Any | None = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        cfg = self._config
        self._connection = self._factory(
            endpoint=cfg.mqtt_endpoint,
            port=cfg.mqtt_port,
            cert_filepath=str(cfg.cert_path),
            pri_key_filepath=str(cfg.key_path),
            ca_filepath=str(cfg.ca_path),
            client_id=cfg.device_id,
            clean_session=False,
            keep_alive_secs=30,
            on_connection_interrupted=self._interrupted,
            on_connection_resumed=self._resumed,
        )
        try:
            self._connection.connect().result(TIMEOUT_S)
        except Exception as exc:
            raise TransportError(f"MQTT connect failed: {type(exc).__name__}") from exc
        self._connected = True

    def disconnect(self) -> None:
        if self._connection is not None and self._connected:
            try:
                self._connection.disconnect().result(TIMEOUT_S)
            finally:
                self._connected = False

    def publish(self, topic: str, payload: bytes) -> None:
        if self._connection is None or not self._connected:
            raise TransportError("not connected")
        try:
            future, _packet_id = self._connection.publish(
                topic=topic, payload=payload, qos=_qos_at_least_once()
            )
            future.result(TIMEOUT_S)
        except Exception as exc:
            raise TransportError(f"publish failed: {type(exc).__name__}") from exc

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        if self._connection is None:
            raise TransportError("not connected")

        def _callback(topic: str, payload: bytes, **_: Any) -> None:
            handler(topic, payload)

        future, _packet_id = self._connection.subscribe(
            topic=topic, qos=_qos_at_least_once(), callback=_callback
        )
        future.result(TIMEOUT_S)

    def _interrupted(self, connection: Any, error: Any, **_: Any) -> None:
        log.warning("MQTT connection interrupted: %s", type(error).__name__)
        self._connected = False

    def _resumed(self, connection: Any, return_code: Any, session_present: bool, **_: Any) -> None:
        log.info("MQTT connection resumed (session_present=%s)", session_present)
        self._connected = True  # the runtime drains its offline buffer on its next send/tick
