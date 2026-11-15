"""Each worker Lambda entry point, end to end through its SQS event shape, with stubbed AWS
clients (botocore Stubber) and in-memory repositories (APP_ENV=test)."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.stub import ANY, Stubber

from application.adapters import memory
from domain.devices import CommandStatus, DeviceCommand
from domain.jobs import Job, JobStatus, JobType
from workers import main
from workers.settings import UnsafeConfigurationError

from ..conftest import FIXTURES
from .test_aws_adapters import FAKE_CREDS

IOT_ENDPOINT = "example-ats.iot.us-east-1.amazonaws.com"


class Clients:
    """client_factory for the workers: one stubbed client per service."""

    def __init__(self) -> None:
        self.clients: dict[str, Any] = {}
        self.stubs: dict[str, Stubber] = {}
        self.requests: list[tuple[str, dict[str, Any]]] = []  # what the workers asked for

    def __call__(self, service: str, **kw: Any) -> Any:
        self.requests.append((service, kw))
        if service not in self.clients:
            self.clients[service] = boto3.client(
                service, region_name="us-east-1", **FAKE_CREDS, **kw
            )
            self.stubs[service] = Stubber(self.clients[service])
            self.stubs[service].activate()
        return self.clients[service]

    def stub(self, service: str) -> Stubber:
        self(service)
        self.requests.pop()
        return self.stubs[service]


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch) -> Iterator[Clients]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("REPOSITORY_BACKEND", "memory")
    monkeypatch.setenv("DEVICE_DATA_BUCKET", "device-data")
    monkeypatch.setenv("IOT_DATA_ENDPOINT", IOT_ENDPOINT)
    fake = Clients()
    main.set_client_factory(fake)
    yield fake
    main.set_client_factory(boto3.client)


def _sqs_event(*bodies: Any) -> dict[str, Any]:
    return {
        "Records": [
            {"messageId": f"m{i}", "body": b if isinstance(b, str) else json.dumps(b)}
            for i, b in enumerate(bodies)
        ]
    }


def _iot_rule_body(topic: str, payload: bytes) -> dict[str, Any]:
    """What the IoT rule forwards to the ingest queue (infrastructure/stacks/iot.py)."""
    return {
        "topic": topic,
        "received_at_ms": 1_794_680_000_000,
        "body_b64": base64.b64encode(payload).decode(),
    }


def test_ingest_lambda_stores_raw_in_s3_and_records_telemetry(clients: Clients) -> None:
    payload = (FIXTURES / "valid" / "telemetry.json").read_bytes()
    stub = clients.stub("s3")
    stub.add_response(
        "put_object",
        {},
        {"Bucket": "device-data", "Key": ANY, "Body": payload, "ContentType": "application/json"},
    )
    stub.add_response(  # the wrong-channel message is quarantined
        "put_object",
        {},
        {
            "Bucket": "device-data",
            "Key": ANY,
            "Body": payload,
            "ContentType": "application/octet-stream",
            "Metadata": ANY,
        },
    )
    event = _sqs_event(
        _iot_rule_body("devices/device-001/telemetry", payload),
        _iot_rule_body("devices/device-001/commands", payload),
        {"not": "an iot rule record"},  # invalid shape: acknowledged, never retried
    )
    assert main.device_message_lambda_handler(event, None) == {"batchItemFailures": []}
    stub.assert_no_pending_responses()
    telemetry = main.lambda_runtime("ingest")[1].telemetry
    assert isinstance(telemetry, memory.InMemoryTelemetryRepository)
    assert telemetry.telemetry


def test_ingest_lambda_reports_s3_outage_as_retryable(clients: Clients) -> None:
    payload = (FIXTURES / "valid" / "telemetry.json").read_bytes()
    clients.stub("s3").add_client_error("put_object", "SlowDown", http_status_code=503)
    event = _sqs_event(_iot_rule_body("devices/device-001/telemetry", payload))
    assert main.device_message_lambda_handler(event, None) == {
        "batchItemFailures": [{"itemIdentifier": "m0"}]
    }


def test_command_lambda_publishes_to_iot_and_marks_sent(clients: Clients) -> None:
    stub = clients.stub("iot-data")
    stub.add_response(
        "publish", {}, {"topic": "devices/device-001/commands", "qos": 1, "payload": ANY}
    )
    commands = main.lambda_runtime("commands")[1].commands
    command = DeviceCommand(project_id="p", device_id="device-001", name="ping", requested_by="u")
    commands.add(command)

    body = {"command_id": command.id}
    # Delivered twice (at-least-once): published once.
    assert main.command_dispatch_lambda_handler(_sqs_event(body, body), None) == {
        "batchItemFailures": []
    }
    stub.assert_no_pending_responses()
    stored = commands.get(command.id)
    assert stored is not None
    assert stored.status is CommandStatus.SENT
    assert ("iot-data", {"endpoint_url": f"https://{IOT_ENDPOINT}"}) in clients.requests


def test_job_lambda_fails_jobs_without_an_executor(clients: Clients) -> None:
    jobs = main.lambda_runtime("jobs")[1].jobs
    job = Job(project_id="p", job_type=JobType.TEST_RUN, created_by="u")
    jobs.add(job)
    event = _sqs_event({"job_id": job.id}, "{broken json")
    assert main.job_lambda_handler(event, None) == {"batchItemFailures": []}
    stored = jobs.get(job.id)
    assert stored is not None
    assert stored.status is JobStatus.FAILED


def test_workers_refuse_to_start_without_their_aws_settings(
    clients: Clients, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("IOT_DATA_ENDPOINT")
    with pytest.raises(UnsafeConfigurationError, match="IOT_DATA_ENDPOINT"):
        main.command_dispatch_lambda_handler(_sqs_event({"command_id": "c"}), None)


def test_workers_refuse_memory_repositories_in_prod(
    clients: Clients, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    with pytest.raises(UnsafeConfigurationError, match="memory"):
        main.device_message_lambda_handler(_sqs_event(), None)


def test_database_url_is_read_from_the_rds_secret(
    clients: Clients, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workers import aws_runtime
    from workers.settings import WorkerSettings

    monkeypatch.setenv("REPOSITORY_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_SECRET_ARN", "arn:secret")
    secret = {"username": "u", "password": "p", "host": "db.example", "port": 5432}
    clients.stub("secretsmanager").add_response(
        "get_secret_value", {"SecretString": json.dumps(secret)}, {"SecretId": "arn:secret"}
    )
    settings = aws_runtime.resolve_settings(WorkerSettings(), clients)
    assert settings.database_url is not None
    assert settings.database_url.get_secret_value() == (
        "postgresql://u:p@db.example:5432/builderwars?sslmode=require"
    )


def test_workers_publish_device_events_only_when_appsync_is_configured() -> None:
    from aws_adapters import AppSyncEventsPublisher
    from workers import aws_runtime
    from workers.settings import WorkerSettings

    assert aws_runtime.device_events(WorkerSettings(app_env="test")) is None
    events = aws_runtime.device_events(
        WorkerSettings(
            app_env="test",
            events_http_dns="abc.appsync-api.us-east-1.amazonaws.com",
            aws_region="us-east-1",
        )
    )
    assert events is not None
    assert isinstance(events._publisher, AppSyncEventsPublisher)
    with pytest.raises(UnsafeConfigurationError, match="AWS_REGION"):
        aws_runtime.device_events(
            WorkerSettings(app_env="test", events_http_dns="abc.example", aws_region=None)
        )
