"""Queue-driven worker Lambdas. Long-running jobs (builds, AI runs) will move to ECS Fargate.

TODO: package dependencies (see stacks/api.py), implement the AWS adapters in
``workers.main`` (handlers currently raise NotImplementedError), add Fargate task definitions
for long-running job types with isolated, least-privilege task roles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aws_cdk import Aws, Duration, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from config import EnvConfig
from constructs import Construct

from stacks.messaging import CONSUMER_TIMEOUT

REPO_ROOT = Path(__file__).resolve().parents[2]


class WorkersStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        config: EnvConfig,
        ingest_queue: sqs.IQueue,
        jobs_queue: sqs.IQueue,
        commands_queue: sqs.IQueue,
        device_data_bucket: s3.IBucket,
        artifacts_bucket: s3.IBucket,
        **kw: Any,
    ) -> None:
        super().__init__(scope, cid, **kw)
        code = lambda_.Code.from_asset(str(REPO_ROOT / "apps/workers/src"))

        ingest_fn = self._function(
            "DeviceIngest", "workers.main.device_message_lambda_handler", code, config
        )
        ingest_fn.add_environment("DEVICE_DATA_BUCKET", device_data_bucket.bucket_name)
        device_data_bucket.grant_put(ingest_fn, "raw/*")
        ingest_fn.add_event_source(
            sources.SqsEventSource(
                ingest_queue,
                batch_size=10,
                max_batching_window=Duration.seconds(5),
                report_batch_item_failures=True,
            )
        )

        commands_fn = self._function(
            "CommandDispatch", "workers.main.command_dispatch_lambda_handler", code, config
        )
        # Only cloud -> device command topics; never device -> cloud topics.
        commands_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["iot:Publish"],
                resources=[
                    f"arn:{Aws.PARTITION}:iot:{Aws.REGION}:{Aws.ACCOUNT_ID}:topic/devices/*/commands"
                ],
            )
        )
        # TODO: IOT_DATA_ENDPOINT env (account-specific ATS endpoint) for the iot-data client.
        commands_fn.add_event_source(
            sources.SqsEventSource(commands_queue, batch_size=10, report_batch_item_failures=True)
        )

        jobs_fn = self._function("Jobs", "workers.main.job_lambda_handler", code, config)
        artifacts_bucket.grant_read_write(jobs_fn)
        jobs_fn.add_event_source(
            sources.SqsEventSource(jobs_queue, batch_size=1, report_batch_item_failures=True)
        )

    def _function(
        self, name: str, handler: str, code: lambda_.Code, config: EnvConfig
    ) -> lambda_.Function:
        return lambda_.Function(
            self,
            f"{name}Function",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler=handler,
            code=code,
            timeout=CONSUMER_TIMEOUT,
            memory_size=256,
            log_group=logs.LogGroup(
                self,
                f"{name}Logs",
                retention=config.log_retention,
                removal_policy=config.removal_policy,
            ),
            environment={"APP_ENV": config.name},
        )
