"""SQS-backed ``JobQueue`` and ``CommandQueue``. Messages carry only the id (the row is the
source of truth); the consuming workers parse them with ``JobMessage`` / ``CommandMessage``."""

from __future__ import annotations

import json
from typing import Any


class SqsJobQueue:
    def __init__(self, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def enqueue(self, job_id: str) -> None:
        self._client.send_message(
            QueueUrl=self._queue_url, MessageBody=json.dumps({"job_id": job_id})
        )


class SqsCommandQueue:
    def __init__(self, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def enqueue_command(self, command_id: str) -> None:
        self._client.send_message(
            QueueUrl=self._queue_url, MessageBody=json.dumps({"command_id": command_id})
        )
