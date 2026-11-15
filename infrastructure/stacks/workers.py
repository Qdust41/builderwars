"""Queue-driven worker Lambdas. Long-running jobs (builds, AI runs) will move to ECS Fargate.

Each function runs ``workers.main.*_lambda_handler`` from a bundled asset (stacks/packaging.py).
With a database (prod) they use PostgreSQL through the RDS secret; without one (dev) they refuse
to start, because in-memory repositories are not allowed outside local/test.

Database connections: every SQS event source is capped at ``MAX_CONCURRENCY`` concurrent
invocations, and each container holds one connection, so the workers use at most ~8 of the
db.t4g.micro's connections.

TODO: Fargate task definitions for long-running job types with isolated, least-privilege roles.
"""

from __future__ import annotations

from typing import Any

from aws_cdk import Aws, CfnParameter, Duration, SecretValue, Stack
from aws_cdk import aws_appsync as appsync
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
from config import EnvConfig
from constructs import Construct

from stacks.api import autofix_secret_arns
from stacks.messaging import AUTOFIX_TIMEOUT, CONSUMER_TIMEOUT
from stacks.packaging import python_app_code

MAX_CONCURRENCY = 2  # the SQS event source minimum


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
        autofix_queue: sqs.IQueue,
        device_data_bucket: s3.IBucket,
        artifacts_bucket: s3.IBucket,
        iot_data_endpoint: str,
        events_api: appsync.EventApi,
        database_secret: secretsmanager.ISecret | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(scope, cid, **kw)
        self._config = config
        self._database_secret = database_secret
        self._code = python_app_code("bw-workers")

        ingest_fn = self._function("DeviceIngest", "workers.main.device_message_lambda_handler")
        ingest_fn.add_environment("DEVICE_DATA_BUCKET", device_data_bucket.bucket_name)
        self._publish_device_events(ingest_fn, events_api)
        device_data_bucket.grant_put(ingest_fn, "raw/*")
        device_data_bucket.grant_put(ingest_fn, "rejected/*")
        # Error logs arriving over MQTT may start auto-fix runs (ADR 0012).
        ingest_fn.add_environment("AUTOFIX_QUEUE_URL", autofix_queue.queue_url)
        autofix_queue.grant_send_messages(ingest_fn)
        ingest_fn.add_event_source(
            sources.SqsEventSource(
                ingest_queue,
                batch_size=10,
                max_batching_window=Duration.seconds(5),
                report_batch_item_failures=True,
                max_concurrency=MAX_CONCURRENCY,
            )
        )

        commands_fn = self._function(
            "CommandDispatch", "workers.main.command_dispatch_lambda_handler"
        )
        commands_fn.add_environment("IOT_DATA_ENDPOINT", iot_data_endpoint)
        self._publish_device_events(commands_fn, events_api)
        # Only cloud -> device command topics; never device -> cloud topics.
        commands_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["iot:Publish"],
                resources=[
                    f"arn:{Aws.PARTITION}:iot:{Aws.REGION}:{Aws.ACCOUNT_ID}:topic/devices/*/commands"
                ],
            )
        )
        commands_fn.add_event_source(
            sources.SqsEventSource(
                commands_queue,
                batch_size=10,
                report_batch_item_failures=True,
                max_concurrency=MAX_CONCURRENCY,
            )
        )

        jobs_fn = self._function("Jobs", "workers.main.job_lambda_handler")
        artifacts_bucket.grant_read_write(jobs_fn)
        jobs_fn.add_event_source(
            sources.SqsEventSource(
                jobs_queue,
                batch_size=1,
                report_batch_item_failures=True,
                max_concurrency=MAX_CONCURRENCY,
            )
        )

        # Auto-fix: logs + repository -> LLM -> pull request. Reads each project's keys (only
        # under this environment's prefix); calls the project's LLM endpoint and GitHub.
        autofix_fn = self._function(
            "AutoFix", "workers.main.autofix_lambda_handler", timeout=AUTOFIX_TIMEOUT
        )
        autofix_fn.add_environment("AUTOFIX_SECRET_PREFIX", config.autofix_secret_prefix)
        # One GitHub token for every project. The deploy workflow passes the
        # AUTOFIX_GITHUB_TOKEN repository secret as this NoEcho parameter (never in the template
        # or the console); a deploy without it keeps the previous value.
        github_token = CfnParameter(
            self,
            "AutoFixGithubToken",
            type="String",
            no_echo=True,
            default="",
            description="GitHub token auto-fix uses for every project without its own",
        )
        shared = secretsmanager.Secret(
            self,
            "AutoFixSharedSecret",
            secret_name=config.autofix_shared_secret_name,
            description="builderwars auto-fix: the GitHub token shared by every project",
            secret_object_value={"github_token": SecretValue.cfn_parameter(github_token)},
            removal_policy=config.removal_policy,
        )
        shared.grant_read(autofix_fn)
        autofix_fn.add_environment("AUTOFIX_SHARED_SECRET_ARN", shared.secret_arn)
        autofix_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[autofix_secret_arns(config)],
            )
        )
        autofix_fn.add_event_source(
            sources.SqsEventSource(
                autofix_queue,
                batch_size=1,
                report_batch_item_failures=True,
                max_concurrency=MAX_CONCURRENCY,
            )
        )

        if database_secret is not None:
            # Applies schema migrations; invoked by hand after a deploy (docs/aws-deployment.md).
            self.migrate_function = self._function(
                "Migrate", "workers.main.migrate_lambda_handler", timeout=Duration.minutes(5)
            )

    @staticmethod
    def _publish_device_events(fn: lambda_.Function, events_api: appsync.EventApi) -> None:
        # Live dashboard: telemetry, logs and command updates go out on AppSync Events.
        fn.add_environment("EVENTS_HTTP_DNS", events_api.http_dns)
        events_api.grant_publish(fn)

    def _function(
        self, name: str, handler: str, *, timeout: Duration = CONSUMER_TIMEOUT
    ) -> lambda_.Function:
        config = self._config
        environment = {"APP_ENV": config.name}
        fn = lambda_.Function(
            self,
            f"{name}Function",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler=handler,
            code=self._code,
            timeout=timeout,
            memory_size=256,
            log_group=logs.LogGroup(
                self,
                f"{name}Logs",
                retention=config.log_retention,
                removal_policy=config.removal_policy,
            ),
            environment=environment,
        )
        if self._database_secret is not None:
            fn.add_environment("REPOSITORY_BACKEND", "postgres")
            fn.add_environment("DATABASE_SECRET_ARN", self._database_secret.secret_arn)
            self._database_secret.grant_read(fn)
        return fn
