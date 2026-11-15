"""API Gateway (HTTP API) + Lambda running FastAPI via Mangum.

The function runs from a bundled asset (stacks/packaging.py). With a database (prod) it uses
PostgreSQL through the RDS secret; it runs outside any VPC and reaches RDS over TLS (ADR 0007).
It enqueues jobs and commands on SQS, records board data that signed-in users upload through the
builderwars CLI (``POST /devices/{id}/messages``), publishes session and device events to
AppSync Events, and verifies
Cognito JWTs itself as well as through the gateway's authorizer (ADR 0005).
"""

from __future__ import annotations

from typing import Any

from aws_cdk import Aws, CfnOutput, Duration, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_appsync as appsync
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
from config import EnvConfig
from constructs import Construct

from stacks.packaging import python_app_code

# Each container holds up to this many database connections (API settings default is 5).
DATABASE_POOL_MAX_SIZE = "2"


def autofix_secret_arns(config: EnvConfig) -> str:
    # Secret ARNs end in a random 6-character suffix, hence the trailing wildcard.
    return (
        f"arn:{Aws.PARTITION}:secretsmanager:{Aws.REGION}:{Aws.ACCOUNT_ID}:secret:"
        f"{config.autofix_secret_prefix}*"
    )


class ApiStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        config: EnvConfig,
        user_pool: cognito.IUserPool,
        user_pool_client: cognito.IUserPoolClient,
        jobs_queue: sqs.IQueue,
        commands_queue: sqs.IQueue,
        autofix_queue: sqs.IQueue,
        artifacts_bucket: s3.IBucket,
        events_api: appsync.EventApi,
        database_secret: secretsmanager.ISecret | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(scope, cid, **kw)
        log_group = logs.LogGroup(
            self,
            "ApiLogs",
            retention=config.log_retention,
            removal_policy=config.removal_policy,
        )
        fn = lambda_.Function(
            self,
            "ApiFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="api.lambda_handler.handler",
            code=python_app_code("bw-api"),
            memory_size=512,
            timeout=Duration.seconds(15),
            log_group=log_group,
            environment={
                "APP_ENV": config.name,
                "AUTH_MODE": "cognito",
                "COGNITO_REGION": self.region,
                "COGNITO_USER_POOL_ID": user_pool.user_pool_id,
                "COGNITO_APP_CLIENT_ID": user_pool_client.user_pool_client_id,
                "REPOSITORY_BACKEND": "postgres",
                "JOBS_QUEUE_URL": jobs_queue.queue_url,
                "COMMANDS_QUEUE_URL": commands_queue.queue_url,
                "ARTIFACTS_BUCKET": artifacts_bucket.bucket_name,
                "EVENTS_HTTP_DNS": events_api.http_dns,
                "AUTOFIX_QUEUE_URL": autofix_queue.queue_url,
                "AUTOFIX_SECRET_PREFIX": config.autofix_secret_prefix,
            },
        )
        if database_secret is not None:
            fn.add_environment("DATABASE_SECRET_ARN", database_secret.secret_arn)
            fn.add_environment("DATABASE_POOL_MAX_SIZE", DATABASE_POOL_MAX_SIZE)
            database_secret.grant_read(fn)
        # Least privilege: enqueue jobs/commands, read artifacts, publish session/device events.
        # The API never publishes to IoT directly; the command dispatcher worker does.
        jobs_queue.grant_send_messages(fn)
        commands_queue.grant_send_messages(fn)
        artifacts_bucket.grant_read(fn)
        # Adding members by email looks accounts up in the pool; read-only, this pool only.
        user_pool.grant(fn, "cognito-idp:ListUsers")
        events_api.grant_publish(fn)
        # Auto-fix (ADR 0012): start runs, and write (never read back to users) each project's
        # LLM key + GitHub token, only under this environment's auto-fix prefix.
        autofix_queue.grant_send_messages(fn)
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "secretsmanager:CreateSecret",
                    "secretsmanager:PutSecretValue",
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DeleteSecret",
                    "secretsmanager:TagResource",
                ],
                resources=[autofix_secret_arns(config)],
            )
        )

        jwt = authorizers.HttpJwtAuthorizer(
            "CognitoJwt",
            jwt_issuer=f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool.user_pool_id}",
            jwt_audience=[user_pool_client.user_pool_client_id],
        )
        http_api = self.http_api = apigw.HttpApi(
            self,
            "HttpApi",
            api_name=config.resource_name("api"),
            default_authorizer=jwt,
            # No CORS: the web app reaches the API same-origin through CloudFront's /api/*
            # behavior (stacks/web.py), and local development goes through the Vite proxy.
        )
        integration = integrations.HttpLambdaIntegration("ApiIntegration", fn)
        http_api.add_routes(
            path="/{proxy+}", methods=[apigw.HttpMethod.ANY], integration=integration
        )
        # Public: liveness, and the sign-in ids the builderwars CLI reads before it logs in.
        for public_path in ("/health", "/client-config"):
            http_api.add_routes(
                path=public_path,
                methods=[apigw.HttpMethod.GET],
                integration=integration,
                authorizer=apigw.HttpNoneAuthorizer(),
            )

        cw.Alarm(
            self,
            "ApiErrors",
            metric=fn.metric_errors(period=Duration.minutes(5)),
            threshold=5,
            evaluation_periods=1,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description="API Lambda is throwing errors",
        )
        CfnOutput(self, "ApiUrl", value=http_api.api_endpoint)
