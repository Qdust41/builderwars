"""``DeviceCommandPublisher`` over the IoT Core data plane (``iot-data`` Publish).

The client must be built with the account's ATS data endpoint
(``boto3.client("iot-data", endpoint_url=f"https://{IOT_DATA_ENDPOINT}")``); the CDK looks it
up at deploy time. The dispatcher's IAM role may publish to ``devices/*/commands`` only.
"""

from __future__ import annotations

from typing import Any

from device_protocol import DeviceEnvelope, MessageType, TopicChannel, topic_for
from device_protocol.codec import encode_message


class IotDataCommandPublisher:
    def __init__(self, client: Any, qos: int = 1) -> None:
        self._client = client
        self._qos = qos

    def publish_command(self, envelope: DeviceEnvelope) -> None:
        if envelope.message_type is not MessageType.COMMAND:
            raise ValueError(f"refusing to publish a {envelope.message_type.value} as a command")
        self._client.publish(
            topic=topic_for(envelope.device_id, TopicChannel.COMMANDS),
            qos=self._qos,
            payload=encode_message(envelope),
        )
