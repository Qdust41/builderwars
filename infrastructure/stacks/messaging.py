"""SQS queues with dead-letter queues and DLQ alarms.

Retry model: consumers use partial batch responses; a message that keeps failing is moved to
the DLQ after ``MAX_RECEIVES`` attempts and the DLQ alarm fires. Handlers are idempotent.
"""

from __future__ import annotations

from typing import Any

from aws_cdk import Duration, Stack
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_sqs as sqs
from config import EnvConfig
from constructs import Construct

MAX_RECEIVES = 5
CONSUMER_TIMEOUT = Duration.seconds(30)


class MessagingStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, config: EnvConfig, **kw: Any) -> None:
        super().__init__(scope, cid, **kw)
        self.ingest_queue, self.ingest_dlq = self._queue_with_dlq("DeviceIngest", config)
        self.jobs_queue, self.jobs_dlq = self._queue_with_dlq("Jobs", config)
        # Device commands (decision #5). Standard queue: per-device FIFO order is enforced by
        # the command records, and expiry is 30 s, so FIFO-queue cost/complexity isn't needed.
        self.commands_queue, self.commands_dlq = self._queue_with_dlq("DeviceCommands", config)

    def _queue_with_dlq(self, name: str, config: EnvConfig) -> tuple[sqs.Queue, sqs.Queue]:
        dlq = sqs.Queue(
            self,
            f"{name}Dlq",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            retention_period=Duration.days(14),
            removal_policy=config.removal_policy,
        )
        queue = sqs.Queue(
            self,
            f"{name}Queue",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            # AWS guidance: >= 6x the consumer Lambda timeout.
            visibility_timeout=Duration.seconds(CONSUMER_TIMEOUT.to_seconds() * 6),
            retention_period=Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=MAX_RECEIVES),
            removal_policy=config.removal_policy,
        )
        cw.Alarm(
            self,
            f"{name}DlqNotEmpty",
            metric=dlq.metric_approximate_number_of_messages_visible(period=Duration.minutes(5)),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description=f"{name} messages are failing repeatedly and landed in the DLQ",
        )
        # Alarm actions are out of MVP scope (decision #13): no SNS wiring yet.
        return queue, dlq
