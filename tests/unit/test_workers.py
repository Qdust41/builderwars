from __future__ import annotations

import json

import pytest

from application.adapters import memory
from domain.jobs import Job, JobStatus, JobType
from workers.consumers import process_sqs_batch
from workers.handlers import BackgroundJobHandler, IncomingDeviceMessage
from workers.handlers.background_job import JobMessage


def test_sqs_batch_reports_only_transient_failures() -> None:
    event = {
        "Records": [
            {"messageId": "ok", "body": json.dumps({"n": 1})},
            {"messageId": "boom", "body": json.dumps({"n": 2})},
            {"messageId": "garbage", "body": "{not json"},
        ]
    }
    seen: list[int] = []

    def handle(body: dict) -> None:
        if body["n"] == 2:
            raise ConnectionError("db down")
        seen.append(body["n"])

    assert process_sqs_batch(event, handle) == {"batchItemFailures": [{"itemIdentifier": "boom"}]}
    assert seen == [1]


def test_incoming_message_rejects_bad_base64() -> None:
    msg = IncomingDeviceMessage(topic="devices/d/telemetry", received_at_ms=0, body_b64="***")
    with pytest.raises(ValueError, match="base64"):
        msg.body()


class _Recorder:
    def __init__(self, output: str | None = "s3://out", fail: bool = False) -> None:
        self.calls = 0
        self._output = output
        self._fail = fail

    def run(self, job: Job) -> str | None:
        self.calls += 1
        if self._fail:
            raise RuntimeError("compiler crashed")
        return self._output


def _job_world(executor=None):
    repo = memory.InMemoryJobRepository()
    job = Job(project_id="p", job_type=JobType.TEST_RUN, created_by="u")
    repo.add(job)
    executors = {JobType.TEST_RUN: executor} if executor else {}
    return repo, job, BackgroundJobHandler(repo, executors)


def test_job_succeeds_and_redelivery_does_not_rerun() -> None:
    executor = _Recorder()
    repo, job, handler = _job_world(executor)
    handler.handle(JobMessage(job_id=job.id))
    handler.handle(JobMessage(job_id=job.id))
    stored = repo.get(job.id)
    assert stored.status is JobStatus.SUCCEEDED
    assert stored.output_reference == "s3://out"
    assert executor.calls == 1


def test_job_without_executor_fails_with_clear_reason() -> None:
    repo, job, handler = _job_world()
    handler.handle(JobMessage(job_id=job.id))
    stored = repo.get(job.id)
    assert stored.status is JobStatus.FAILED
    assert "not implemented" in stored.error_summary


def test_executor_exception_marks_job_failed() -> None:
    repo, job, handler = _job_world(_Recorder(fail=True))
    handler.handle(JobMessage(job_id=job.id))
    assert repo.get(job.id).status is JobStatus.FAILED
    assert repo.get(job.id).error_summary == "RuntimeError"


def test_unknown_job_id_is_dropped() -> None:
    _, _, handler = _job_world()
    assert handler.handle(JobMessage(job_id="job_missing")) is None


def _queued_command(repo, **kw):
    from domain.devices import DeviceCommand

    command = DeviceCommand(project_id="p", device_id="dev-1", name="ping", requested_by="u", **kw)
    repo.add(command)
    return command


def test_command_dispatch_publishes_once_and_marks_sent() -> None:
    from device_protocol import MessageType
    from domain.devices import CommandStatus
    from workers.handlers import CommandDispatchHandler, CommandMessage

    repo = memory.InMemoryDeviceCommandRepository()
    publisher = memory.RecordingCommandPublisher()
    command = _queued_command(repo)
    handler = CommandDispatchHandler(repo, publisher)
    handler.handle(CommandMessage(command_id=command.id))
    handler.handle(CommandMessage(command_id=command.id))  # redelivery
    [envelope] = publisher.commands
    assert envelope.device_id == "dev-1"
    assert envelope.message_type is MessageType.COMMAND
    assert envelope.payload["command_id"] == command.id
    assert repo.get(command.id).status is CommandStatus.SENT


def test_expired_command_times_out_instead_of_sending() -> None:
    from datetime import UTC, datetime, timedelta

    from domain.devices import CommandStatus
    from workers.handlers import CommandDispatchHandler, CommandMessage

    repo = memory.InMemoryDeviceCommandRepository()
    publisher = memory.RecordingCommandPublisher()
    created = datetime(2026, 11, 14, tzinfo=UTC)
    command = _queued_command(repo, created_at=created)
    CommandDispatchHandler(repo, publisher).handle(
        CommandMessage(command_id=command.id), now=created + timedelta(minutes=5)
    )
    assert publisher.commands == []
    assert repo.get(command.id).status is CommandStatus.TIMED_OUT
