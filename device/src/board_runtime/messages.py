from __future__ import annotations

from datetime import datetime
from typing import Any

from board_runtime.config import DeviceConfig
from board_runtime.sequence import MemorySequenceStore, SequenceStore
from device_protocol import DeviceEnvelope, MessageType, encode_message, topic_for_message
from device_protocol.compat import UTC
from device_protocol.schemas import validate_payload


class MessageFactory:
    """Builds valid, sequenced envelopes for this device.

    One sequence number per published message (a telemetry batch is one message). Use a
    ``FileSequenceStore`` on real hosts so numbers survive reboots (decision #14).
    """

    def __init__(self, config: DeviceConfig, sequence: SequenceStore | None = None) -> None:
        self._config = config
        self._sequence = sequence or MemorySequenceStore()

    def build(self, message_type: MessageType, payload: dict[str, Any]) -> tuple[str, bytes]:
        validate_payload(message_type, payload)  # fail on the host, not in the cloud
        envelope = DeviceEnvelope.new(
            device_id=self._config.device_id,
            message_type=message_type,
            payload=payload,
            sequence_number=self._sequence.next(),
            firmware_version=self._config.firmware_version,
            hardware_model=self._config.hardware_model,
            timestamp=datetime.now(UTC),
        )
        return topic_for_message(self._config.device_id, message_type), encode_message(envelope)
