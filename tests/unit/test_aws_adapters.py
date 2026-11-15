"""AWS adapters against botocore Stubbers: real client models, no network, no credentials."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from botocore.credentials import Credentials
from botocore.stub import ANY, Stubber

from application.realtime import RealtimeEvent, RealtimeEventType
from aws_adapters import (
    AppSyncEventsPublisher,
    IotDataCommandPublisher,
    S3RawMessageStore,
    SqsCommandQueue,
    SqsJobQueue,
    database_url_from_secret,
)
from aws_adapters.appsync import RealtimePublishError
from device_protocol import DeviceEnvelope, MessageType

AT = datetime(2026, 11, 14, 18, 30, 5, tzinfo=UTC)
FAKE_CREDS = {"aws_access_key_id": "testing", "aws_secret_access_key": "testing"}


def client(service: str, **kw: Any) -> Any:
    return boto3.client(service, region_name="us-east-1", **FAKE_CREDS, **kw)


def test_s3_raw_store_writes_deterministic_raw_key() -> None:
    s3 = client("s3")
    with Stubber(s3) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "bucket",
                "Key": "raw/device-001/2026/11/14/m-1.json",
                "Body": b"{}",
                "ContentType": "application/json",
            },
        )
        S3RawMessageStore(s3, "bucket").put(
            device_id="device-001", message_id="m-1", received_at=AT, body=b"{}"
        )
        stub.assert_no_pending_responses()


@pytest.mark.parametrize(
    ("device_id", "folder"),
    [("device-001", "device-001"), (None, "_unknown"), ("../etc", "_invalid")],
)
def test_s3_quarantine_goes_under_rejected_with_reason(device_id: str | None, folder: str) -> None:
    s3 = client("s3")
    with Stubber(s3) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "bucket",
                "Key": ANY,
                "Body": b"junk",
                "ContentType": "application/octet-stream",
                "Metadata": {"reason": "invalid_json"},
            },
        )
        captured: dict[str, Any] = {}
        s3.meta.events.register(
            "provide-client-params.s3.PutObject", lambda params, **_: captured.update(params)
        )
        S3RawMessageStore(s3, "bucket").quarantine(
            device_id=device_id, received_at=AT, body=b"junk", reason="invalid_json"
        )
    assert captured["Key"].startswith(f"rejected/{folder}/2026/11/14/")
    assert captured["Key"].endswith(".bin")


def test_sqs_queues_send_only_the_id() -> None:
    sqs = client("sqs")
    url = "https://sqs.us-east-1.amazonaws.com/000000000000/jobs"
    with Stubber(sqs) as stub:
        stub.add_response(
            "send_message",
            {"MessageId": "1"},
            {"QueueUrl": url, "MessageBody": json.dumps({"job_id": "job-1"})},
        )
        stub.add_response(
            "send_message",
            {"MessageId": "2"},
            {"QueueUrl": url, "MessageBody": json.dumps({"command_id": "cmd-1"})},
        )
        SqsJobQueue(sqs, url).enqueue("job-1")
        SqsCommandQueue(sqs, url).enqueue_command("cmd-1")
        stub.assert_no_pending_responses()


def _command_envelope(message_type: MessageType = MessageType.COMMAND) -> DeviceEnvelope:
    return DeviceEnvelope.new(
        device_id="device-001",
        message_type=message_type,
        payload={"command_id": "00000000-0000-4000-8000-000000000009", "name": "ping"},
        timestamp=AT,
    )


def test_iot_publisher_sends_to_the_device_command_topic() -> None:
    iot = client("iot-data", endpoint_url="https://example-ats.iot.us-east-1.amazonaws.com")
    envelope = _command_envelope()
    with Stubber(iot) as stub:
        stub.add_response(
            "publish",
            {},
            {"topic": "devices/device-001/commands", "qos": 1, "payload": ANY},
        )
        IotDataCommandPublisher(iot).publish_command(envelope)
        stub.assert_no_pending_responses()


def test_iot_publisher_refuses_non_command_envelopes() -> None:
    iot = client("iot-data", endpoint_url="https://example-ats.iot.us-east-1.amazonaws.com")
    with Stubber(iot), pytest.raises(ValueError, match="command"):
        IotDataCommandPublisher(iot).publish_command(_command_envelope(MessageType.LOG))


def test_database_url_comes_from_the_rds_secret_with_tls() -> None:
    sm = client("secretsmanager")
    secret = {
        "username": "builderwars_admin",
        "password": "p@ss/word",
        "host": "db.example.us-east-1.rds.amazonaws.com",
        "port": 5432,
        "dbname": "builderwars",
    }
    with Stubber(sm) as stub:
        stub.add_response(
            "get_secret_value",
            {"SecretString": json.dumps(secret)},
            {"SecretId": "arn:secret"},
        )
        url = database_url_from_secret(sm, "arn:secret")
    assert url == (
        "postgresql://builderwars_admin:p%40ss%2Fword@db.example.us-east-1.rds.amazonaws.com"
        ":5432/builderwars?sslmode=require"
    )


class _FakeSender:
    def __init__(self, status: int = 200, body: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []
        self._status = status
        self._body = body if body is not None else {"successful": [{"index": 0}], "failed": []}

    def __call__(
        self, url: str, body: bytes, headers: dict[str, str], timeout: float
    ) -> tuple[int, bytes]:
        self.calls.append((url, body, headers))
        return self._status, json.dumps(self._body).encode()


def _event() -> RealtimeEvent:
    return RealtimeEvent(
        type=RealtimeEventType.USER_JOINED, project_id="prj_1", session_id="ses_1", actor_id="u"
    )


def _publisher(sender: _FakeSender) -> AppSyncEventsPublisher:
    return AppSyncEventsPublisher(
        http_dns="abc.appsync-api.us-east-1.amazonaws.com",
        region="us-east-1",
        credentials=lambda: Credentials("testing", "testing"),
        send=sender,
    )


def test_appsync_publish_is_sigv4_signed_to_the_session_channel() -> None:
    sender = _FakeSender()
    event = _event()
    _publisher(sender).publish(event)
    [(url, body, headers)] = sender.calls
    assert url == "https://abc.appsync-api.us-east-1.amazonaws.com/event"
    payload = json.loads(body)
    # AppSync channel segments allow only [A-Za-z0-9-], so ids spell "_" as "-" (ADR 0008).
    assert payload["channel"] == "/projects/prj-1/sessions/ses-1"
    assert json.loads(payload["events"][0])["event_id"] == str(event.event_id)
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 ")
    assert "/appsync/aws4_request" in headers["Authorization"]


@pytest.mark.parametrize(
    "sender",
    [_FakeSender(status=401), _FakeSender(body={"successful": [], "failed": [{"index": 0}]})],
)
def test_appsync_publish_failures_raise(sender: _FakeSender) -> None:
    with pytest.raises(RealtimePublishError):
        _publisher(sender).publish(_event())
