"""MQTT topic namespace shared by the board and the cloud.

Layout: ``devices/{device_id}/{channel}``.

Device identity comes from the authenticated MQTT connection: the AWS IoT policy only allows a
device to publish/subscribe under its own ``devices/{thing_name}/...`` prefix. Consumers must take
the device id from the *topic* (which the broker authorised), never from the payload.
"""

from __future__ import annotations

import re
from typing import Final

from device_protocol.compat import StrEnum
from device_protocol.envelopes import MessageType

TOPIC_ROOT: Final[str] = "devices"

# Matches AWS IoT thing-name rules minus ":" (kept out so ids are safe in topics and URLs).
DEVICE_ID_PATTERN: Final[str] = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
_DEVICE_ID_RE = re.compile(DEVICE_ID_PATTERN)


class TopicChannel(StrEnum):
    TELEMETRY = "telemetry"
    LOGS = "logs"
    STATUS = "status"
    EVENTS = "events"
    COMMANDS = "commands"  # cloud -> device
    RESPONSES = "responses"  # device -> cloud (command results)


DEVICE_TO_CLOUD_CHANNELS: Final[frozenset[TopicChannel]] = frozenset(
    {
        TopicChannel.TELEMETRY,
        TopicChannel.LOGS,
        TopicChannel.STATUS,
        TopicChannel.EVENTS,
        TopicChannel.RESPONSES,
    }
)

CHANNEL_FOR_MESSAGE_TYPE: Final[dict[MessageType, TopicChannel]] = {
    MessageType.TELEMETRY: TopicChannel.TELEMETRY,
    MessageType.LOG: TopicChannel.LOGS,
    MessageType.STATUS: TopicChannel.STATUS,
    MessageType.HEARTBEAT: TopicChannel.STATUS,
    MessageType.EVENT: TopicChannel.EVENTS,
    MessageType.COMMAND: TopicChannel.COMMANDS,
    MessageType.COMMAND_RESULT: TopicChannel.RESPONSES,
}


class InvalidTopicError(ValueError):
    pass


def validate_device_id(device_id: str) -> str:
    if not _DEVICE_ID_RE.fullmatch(device_id):
        raise InvalidTopicError(f"invalid device id {device_id!r}")
    return device_id


def topic_for(device_id: str, channel: TopicChannel) -> str:
    return f"{TOPIC_ROOT}/{validate_device_id(device_id)}/{channel.value}"


def topic_for_message(device_id: str, message_type: MessageType) -> str:
    return topic_for(device_id, CHANNEL_FOR_MESSAGE_TYPE[message_type])


def parse_topic(topic: str) -> tuple[str, TopicChannel]:
    """Split a concrete topic into ``(device_id, channel)``; raise on anything unexpected."""
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != TOPIC_ROOT:
        raise InvalidTopicError(f"unexpected topic {topic!r}")
    _, device_id, channel = parts
    try:
        parsed_channel = TopicChannel(channel)
    except ValueError as exc:
        raise InvalidTopicError(f"unknown channel in topic {topic!r}") from exc
    return validate_device_id(device_id), parsed_channel


def channel_accepts(channel: TopicChannel, message_type: MessageType) -> bool:
    """Whether a message of ``message_type`` is allowed on ``channel``."""
    return CHANNEL_FOR_MESSAGE_TYPE[message_type] is channel
