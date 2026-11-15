"""The API's deployed wiring: SQS queues and the AppSync publisher, with stubbed clients."""

from __future__ import annotations

import json
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber

from api.dependencies import _aws_messaging, build_container
from api.settings import (
    AppEnv,
    AuthMode,
    RepositoryBackend,
    Settings,
    UnsafeConfigurationError,
    validate_settings,
)
from aws_adapters import AppSyncEventsPublisher
from domain.jobs import JobType

from .test_aws_adapters import FAKE_CREDS

JOBS_URL = "https://sqs.us-east-1.amazonaws.com/000000000000/jobs"
COMMANDS_URL = "https://sqs.us-east-1.amazonaws.com/000000000000/commands"


def _aws_settings(**kw: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": AppEnv.TEST,
        "jobs_queue_url": JOBS_URL,
        "commands_queue_url": COMMANDS_URL,
        "events_http_dns": "abc.appsync-api.us-east-1.amazonaws.com",
        "aws_region": "us-east-1",
    }
    values.update(kw)
    return Settings(**values)


def test_deployed_api_refuses_to_start_without_queues_and_events() -> None:
    with pytest.raises(UnsafeConfigurationError, match=r"JOBS_QUEUE_URL.*EVENTS_HTTP_DNS"):
        validate_settings(
            Settings(
                app_env=AppEnv.PROD,
                auth_mode=AuthMode.COGNITO,
                repository_backend=RepositoryBackend.POSTGRES,
                database_url="postgresql://u:p@db/x",
                commands_queue_url=COMMANDS_URL,
                aws_region="us-east-1",
            )
        )


def test_jobs_created_through_the_api_services_land_on_sqs() -> None:
    sqs = boto3.client("sqs", region_name="us-east-1", **FAKE_CREDS)
    settings = _aws_settings()
    messaging = _aws_messaging(settings, lambda service, **_: sqs)
    assert isinstance(messaging.realtime, AppSyncEventsPublisher)

    container = build_container(settings, messaging=messaging)
    project = container.projects.create_project(user_id="alice", name="Rover")
    with Stubber(sqs) as stub:
        # The job id is minted inside the service, so capture the request instead of
        # predicting it.
        sent: list[dict[str, Any]] = []
        sqs.meta.events.register(
            "provide-client-params.sqs.SendMessage", lambda params, **_: sent.append(params)
        )
        stub.add_response("send_message", {"MessageId": "1"})
        job = container.jobs.create_job(
            user_id="alice", project_id=project.id, job_type=JobType.TEST_RUN
        )
    assert sent == [{"QueueUrl": JOBS_URL, "MessageBody": json.dumps({"job_id": job.id})}]
