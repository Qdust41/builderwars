"""Decode/encode raw device messages with explicit, typed rejection reasons.

Malformed or unsupported messages are never partially processed. Callers get a
``MessageValidationError`` whose ``reason`` says whether retrying could ever help
(it can't: every reason here is permanent) so workers can drop/park them instead of retrying.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from device_protocol.compat import StrEnum
from device_protocol.envelopes import MAX_MESSAGE_BYTES, DeviceEnvelope
from device_protocol.schemas import validate_payload
from device_protocol.versioning import is_supported


class RejectionReason(StrEnum):
    TOO_LARGE = "too_large"
    MALFORMED_JSON = "malformed_json"
    UNSUPPORTED_VERSION = "unsupported_version"
    INVALID_ENVELOPE = "invalid_envelope"
    INVALID_PAYLOAD = "invalid_payload"
    IDENTITY_MISMATCH = "identity_mismatch"
    WRONG_CHANNEL = "wrong_channel"
    UNKNOWN_DEVICE = "unknown_device"  # the topic's device id is not registered
    DEVICE_REVOKED = "device_revoked"  # the device was revoked; history is kept


class MessageValidationError(ValueError):
    def __init__(self, reason: RejectionReason, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class DecodedMessage:
    envelope: DeviceEnvelope
    payload: BaseModel


def decode_message(raw: bytes | str | dict[str, Any]) -> DecodedMessage:
    if isinstance(raw, dict):
        data: Any = raw
    else:
        raw_bytes = raw.encode() if isinstance(raw, str) else raw
        if len(raw_bytes) > MAX_MESSAGE_BYTES:
            raise MessageValidationError(
                RejectionReason.TOO_LARGE,
                f"message is {len(raw_bytes)} bytes; limit is {MAX_MESSAGE_BYTES}",
            )
        try:
            data = json.loads(raw_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MessageValidationError(RejectionReason.MALFORMED_JSON, str(exc)) from exc

    if not isinstance(data, dict):
        raise MessageValidationError(RejectionReason.MALFORMED_JSON, "message must be an object")

    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or not is_supported(version):
        raise MessageValidationError(
            RejectionReason.UNSUPPORTED_VERSION, f"schema_version={version!r}"
        )

    try:
        envelope = DeviceEnvelope.model_validate(data)
    except ValidationError as exc:
        raise MessageValidationError(RejectionReason.INVALID_ENVELOPE, _summary(exc)) from exc

    try:
        payload = validate_payload(envelope.message_type, envelope.payload)
    except (ValidationError, ValueError) as exc:
        detail = _summary(exc) if isinstance(exc, ValidationError) else str(exc)
        raise MessageValidationError(RejectionReason.INVALID_PAYLOAD, detail) from exc

    return DecodedMessage(envelope=envelope, payload=payload)


def encode_message(envelope: DeviceEnvelope) -> bytes:
    data = envelope.model_dump_json().encode()
    if len(data) > MAX_MESSAGE_BYTES:
        raise MessageValidationError(
            RejectionReason.TOO_LARGE, f"encoded message is {len(data)} bytes"
        )
    return data


def _summary(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
        for err in exc.errors()[:5]
    )
