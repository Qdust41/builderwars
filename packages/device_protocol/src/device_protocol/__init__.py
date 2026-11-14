"""Shared, versioned device <-> cloud message contracts.

This package is the single source of truth for the protocol. The JSON Schemas under
``contracts/device`` are generated from these models (``scripts/export_contracts.py``) and a
contract test fails if they drift.
"""

from device_protocol.codec import (
    DecodedMessage,
    MessageValidationError,
    RejectionReason,
    decode_message,
    encode_message,
)
from device_protocol.envelopes import (
    MAX_MESSAGE_BYTES,
    MAX_PAYLOAD_BYTES,
    DeviceEnvelope,
    MessageType,
)
from device_protocol.topics import TopicChannel, parse_topic, topic_for, topic_for_message
from device_protocol.versioning import CURRENT_SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "MAX_MESSAGE_BYTES",
    "MAX_PAYLOAD_BYTES",
    "SUPPORTED_SCHEMA_VERSIONS",
    "DecodedMessage",
    "DeviceEnvelope",
    "MessageType",
    "MessageValidationError",
    "RejectionReason",
    "TopicChannel",
    "decode_message",
    "encode_message",
    "parse_topic",
    "topic_for",
    "topic_for_message",
]
