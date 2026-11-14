from __future__ import annotations

import json
from pathlib import Path

import pytest

from device_protocol import (
    MAX_MESSAGE_BYTES,
    MAX_PAYLOAD_BYTES,
    DeviceEnvelope,
    MessageType,
    MessageValidationError,
    RejectionReason,
    decode_message,
    encode_message,
    parse_topic,
    topic_for,
    topic_for_message,
)
from device_protocol.topics import InvalidTopicError, TopicChannel

pytestmark = pytest.mark.contract

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "device" / "fixtures"

VALID = sorted((FIXTURES / "valid").glob("*.json"))
INVALID = sorted((FIXTURES / "invalid").glob("*.json"))


def test_fixture_sets_cover_every_message_type() -> None:
    covered = {json.loads(p.read_text())["message_type"] for p in VALID}
    assert covered == {t.value for t in MessageType}
    assert INVALID, "expected invalid fixtures"


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_valid_fixtures_decode_and_round_trip(path: Path) -> None:
    decoded = decode_message(path.read_bytes())
    again = decode_message(encode_message(decoded.envelope))
    assert again.envelope == decoded.envelope


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_invalid_fixtures_are_rejected_with_expected_reason(path: Path) -> None:
    expected = RejectionReason(path.stem.split("__")[0])
    with pytest.raises(MessageValidationError) as info:
        decode_message(path.read_bytes())
    assert info.value.reason is expected


def test_oversized_raw_message_is_rejected_before_parsing() -> None:
    with pytest.raises(MessageValidationError) as info:
        decode_message(b" " * (MAX_MESSAGE_BYTES + 1))
    assert info.value.reason is RejectionReason.TOO_LARGE


def test_oversized_payload_is_rejected() -> None:
    data = json.loads((FIXTURES / "valid" / "telemetry.json").read_text())
    data["payload"] = {
        "samples": [
            {"ts": "2026-11-14T18:30:00Z", "readings": {"blob": "x" * (MAX_PAYLOAD_BYTES + 1)}}
        ]
    }
    with pytest.raises(MessageValidationError) as info:
        decode_message(data)
    assert info.value.reason is RejectionReason.INVALID_ENVELOPE


def test_boolean_schema_version_is_not_treated_as_one() -> None:
    data = json.loads((FIXTURES / "valid" / "telemetry.json").read_text())
    data["schema_version"] = True
    with pytest.raises(MessageValidationError) as info:
        decode_message(data)
    assert info.value.reason is RejectionReason.UNSUPPORTED_VERSION


def test_envelope_new_produces_unique_ids() -> None:
    a = DeviceEnvelope.new(
        device_id="d", message_type=MessageType.HEARTBEAT, payload={"uptime_s": 1}
    )
    b = DeviceEnvelope.new(
        device_id="d", message_type=MessageType.HEARTBEAT, payload={"uptime_s": 1}
    )
    assert a.message_id != b.message_id
    assert a.idempotency_key == f"d:{a.message_id}"


@pytest.mark.parametrize(
    ("message_type", "topic"),
    [
        (MessageType.TELEMETRY, "devices/device-001/telemetry"),
        (MessageType.LOG, "devices/device-001/logs"),
        (MessageType.STATUS, "devices/device-001/status"),
        (MessageType.HEARTBEAT, "devices/device-001/status"),
        (MessageType.EVENT, "devices/device-001/events"),
        (MessageType.COMMAND, "devices/device-001/commands"),
        (MessageType.COMMAND_RESULT, "devices/device-001/responses"),
    ],
)
def test_topic_for_message(message_type: MessageType, topic: str) -> None:
    assert topic_for_message("device-001", message_type) == topic
    assert parse_topic(topic)[0] == "device-001"


@pytest.mark.parametrize(
    "topic",
    ["devices/+/telemetry", "devices/a/b/telemetry", "things/a/telemetry", "devices/a/firmware"],
)
def test_parse_topic_rejects_unexpected_topics(topic: str) -> None:
    with pytest.raises(InvalidTopicError):
        parse_topic(topic)


def test_topic_for_refuses_wildcards_in_device_id() -> None:
    with pytest.raises(InvalidTopicError):
        topic_for("#", TopicChannel.TELEMETRY)


def test_schema_version_check_comes_before_payload_shape() -> None:
    data = json.loads((FIXTURES / "valid" / "telemetry.json").read_text())
    data["schema_version"] = 2
    data["payload"] = {"anything": "goes"}
    with pytest.raises(MessageValidationError) as info:
        decode_message(data)
    assert info.value.reason is RejectionReason.UNSUPPORTED_VERSION


def test_strenum_values_serialise_as_plain_strings() -> None:
    # Guards the Python 3.10 StrEnum backport in device_protocol.compat.
    assert str(MessageType.TELEMETRY) == "telemetry"
    assert json.dumps({"t": MessageType.EVENT}) == '{"t": "event"}'
