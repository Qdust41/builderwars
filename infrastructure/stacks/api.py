"""API Gateway (HTTP API) + Lambda running FastAPI via Mangum.

TODO before first deploy:
* Package dependencies: build a Lambda asset from ``uv export`` + ``pip install --target`` (or a
  container image from docker/api.Dockerfile). The asset below is source only.
* Implement Cognito auth mode and PostgreSQL repositories in the API; the app intentionally
  refuses to start in non-local environments until then.
* Give the function VPC access when RDS is enabled.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from config import EnvConfig
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[2]


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
        artifacts_bucket: s3.IBucket,
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
            code=lambda_.Code.from_asset(str(REPO_ROOT / "apps/api/src")),
            memory_size=512,
            timeout=Duration.seconds(15),
            log_group=log_group,
            environment={
                "APP_ENV": config.name,
                "AUTH_MODE": "cognito",
                "REPOSITORY_BACKEND": "postgres",
                "JOBS_QUEUE_URL": jobs_queue.queue_url,
                "COMMANDS_QUEUE_URL": commands_queue.queue_url,
                "ARTIFACTS_BUCKET": artifacts_bucket.bucket_name,
            },
        )
        # Least privilege: enqueue jobs/commands and read artifacts. The API never publishes to
        # IoT directly; the command dispatcher worker does.
        jobs_queue.grant_send_messages(fn)
        commands_queue.grant_send_messages(fn)
        artifacts_bucket.grant_read(fn)

        jwt = authorizers.HttpJwtAuthorizer(
            "CognitoJwt",
            jwt_issuer=f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool.user_pool_id}",
            jwt_audience=[user_pool_client.user_pool_client_id],
        )
        http_api = apigw.HttpApi(
            self,
            "HttpApi",
            api_name=config.resource_name("api"),
            default_authorizer=jwt,
            # TODO: restrict CORS origins to the deployed web app domain.
        )
        integration = integrations.HttpLambdaIntegration("ApiIntegration", fn)
        http_api.add_routes(
            path="/{proxy+}", methods=[apigw.HttpMethod.ANY], integration=integration
        )
        http_api.add_routes(
            path="/health",
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
