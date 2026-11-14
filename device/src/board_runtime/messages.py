from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any

from board_runtime.config import DeviceConfig
from device_protocol import DeviceEnvelope, MessageType, encode_message, topic_for_message
from device_protocol.schemas import validate_payload


class MessageFactory:
    """Builds valid, sequenced envelopes for this device.

    The sequence number is per-process. TODO: persist it across reboots if consumers need
    gap detection (depends on board storage, open decision #1).
    """

    def __init__(self, config: DeviceConfig, *, start_sequence: int = 0) -> None:
        self._config = config
        self._seq = itertools.count(start_sequence)

    def build(self, message_type: MessageType, payload: dict[str, Any]) -> tuple[str, bytes]:
        validate_payload(message_type, payload)  # fail on the board, not in the cloud
        envelope = DeviceEnvelope.new(
            device_id=self._config.device_id,
            message_type=message_type,
            payload=payload,
            sequence_number=next(self._seq),
            firmware_version=self._config.firmware_version,
            hardware_model=self._config.hardware_model,
            timestamp=datetime.now(UTC),
        )
        return topic_for_message(self._config.device_id, message_type), encode_message(envelope)
