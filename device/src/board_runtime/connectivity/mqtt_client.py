"""AWS IoT Core MQTT transport — STUB.

Not implemented. Library choice depends on the board OS/Python (open decision #1): candidates
are ``awsiotsdk`` (AWS IoT Device SDK v2) on CPython, or ``umqtt`` on MicroPython.

Implementation notes for whoever fills this in:
* Mutual TLS with the per-device X.509 certificate; client id MUST equal the IoT thing name,
  because the IoT policy authorises ``client/${iot:Connection.Thing.ThingName}``.
* QoS 1 for telemetry/logs/status/responses; the cloud deduplicates (at-least-once).
* On disconnect: back off with ``BackoffPolicy`` and queue outgoing messages in the
  ``OfflineBuffer``; drain the buffer in order once reconnected.
* Subscribe to ``devices/{device_id}/commands`` and route to ``CommandDispatcher``.
* Never log certificate/key contents.
"""

from __future__ import annotations

from board_runtime.config import DeviceConfig
from board_runtime.connectivity.transport import MessageHandler


class MqttTransport:
    def __init__(self, config: DeviceConfig) -> None:
        config.validate()
        self._config = config

    @property
    def connected(self) -> bool:
        return False

    def connect(self) -> None:
        raise NotImplementedError("MQTT/TLS transport to AWS IoT Core is not implemented yet")

    def disconnect(self) -> None:
        pass

    def publish(self, topic: str, payload: bytes) -> None:
        raise NotImplementedError("MQTT/TLS transport to AWS IoT Core is not implemented yet")

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        raise NotImplementedError("MQTT/TLS transport to AWS IoT Core is not implemented yet")
