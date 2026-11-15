"""Synthesis tests: build templates in memory and check the safety properties. No AWS calls."""

from __future__ import annotations

import json

import aws_cdk as cdk
import pytest
from app import build
from aws_cdk.assertions import Match, Template
from config import get_config


def new_app() -> cdk.App:
    """An app that skips asset bundling (no uv/pip/network in template assertions)."""
    return cdk.App(context={"aws:cdk:bundling-stacks": []})


@pytest.fixture(scope="module", params=["dev", "prod"])
def stacks(request: pytest.FixtureRequest) -> dict[str, Template]:
    app = new_app()
    built = build(app, get_config(request.param))
    return {name: Template.from_stack(stack) for name, stack in built.items()}


def test_rds_only_when_enabled() -> None:
    assert "database" not in build(new_app(), get_config("dev"))
    with pytest.raises(ValueError, match="unknown env"):
        get_config("staging")  # no deployed staging for the MVP (decision #12)
    assert "database" in build(new_app(), get_config("prod"))


def test_buckets_are_private_encrypted_and_tls_only(stacks: dict[str, Template]) -> None:
    storage = stacks["storage"]
    storage.resource_count_is("AWS::S3::Bucket", 2)
    storage.all_resources_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "BucketEncryption": Match.any_value(),
            "LifecycleConfiguration": Match.any_value(),
        },
    )
    policies = json.dumps(storage.find_resources("AWS::S3::BucketPolicy"))
    assert "aws:SecureTransport" in policies


def test_every_queue_has_a_dlq_and_alarm(stacks: dict[str, Template]) -> None:
    messaging = stacks["messaging"]
    messaging.resource_count_is("AWS::SQS::Queue", 6)
    messaging.resource_properties_count_is(
        "AWS::SQS::Queue", {"RedrivePolicy": Match.object_like({"maxReceiveCount": 5})}, 3
    )
    messaging.resource_count_is("AWS::CloudWatch::Alarm", 3)


def test_device_policy_is_scoped_to_its_own_thing(stacks: dict[str, Template]) -> None:
    [policy] = stacks["iot"].find_resources("AWS::IoT::Policy").values()
    doc = json.dumps(policy["Properties"]["PolicyDocument"])
    assert "${iot:Connection.Thing.ThingName}" in doc
    for wildcard in ("devices/+", "devices/#", '"*"'):
        assert wildcard not in doc
    statements = policy["Properties"]["PolicyDocument"]["Statement"]
    publish = next(s for s in statements if s["Action"] == "iot:Publish")
    assert not any("commands" in json.dumps(r) for r in publish["Resource"])


def test_ingest_rule_excludes_command_topic(stacks: dict[str, Template]) -> None:
    [rule] = stacks["iot"].find_resources("AWS::IoT::TopicRule").values()
    sql = rule["Properties"]["TopicRulePayload"]["Sql"]
    assert "commands" not in sql
    assert "encode(*, 'base64') AS body_b64" in sql


def test_realtime_publish_is_backend_only(stacks: dict[str, Template]) -> None:
    stacks["realtime"].has_resource_properties(
        "AWS::AppSync::Api",
        {
            "EventConfig": Match.object_like(
                {
                    "DefaultPublishAuthModes": [{"AuthType": "AWS_IAM"}],
                    "DefaultSubscribeAuthModes": [{"AuthType": "AMAZON_COGNITO_USER_POOLS"}],
                }
            )
        },
    )


def test_api_routes_require_jwt_except_health(stacks: dict[str, Template]) -> None:
    api = stacks["api"]
    api.has_resource_properties("AWS::ApiGatewayV2::Authorizer", {"AuthorizerType": "JWT"})
    api.has_resource_properties(
        "AWS::ApiGatewayV2::Route", {"RouteKey": "ANY /{proxy+}", "AuthorizationType": "JWT"}
    )
    api.has_resource_properties(
        "AWS::ApiGatewayV2::Route", {"RouteKey": "GET /health", "AuthorizationType": "NONE"}
    )
    api.has_resource_properties(
        "AWS::Lambda::Function",
        {"Environment": {"Variables": Match.object_like({"AUTH_MODE": "cognito"})}},
    )


def test_database_is_tls_only_encrypted_and_only_opens_postgres() -> None:
    # Publicly reachable by owner decision (ADR 0007); TLS is what protects it.
    template = Template.from_stack(build(new_app(), get_config("prod"))["database"])
    template.has_resource_properties(
        "AWS::RDS::DBInstance",
        {"PubliclyAccessible": True, "StorageEncrypted": True, "DeletionProtection": True},
    )
    template.has_resource_properties(
        "AWS::RDS::DBParameterGroup", {"Parameters": {"rds.force_ssl": "1"}}
    )
    [group] = template.find_resources("AWS::EC2::SecurityGroup").values()
    ingress = group["Properties"]["SecurityGroupIngress"]
    assert [(r["FromPort"], r["ToPort"], r["IpProtocol"]) for r in ingress] == [(5432, 5432, "tcp")]
    template.resource_count_is("AWS::EC2::NatGateway", 0)


def _functions(template: Template) -> dict[str, dict]:
    return {
        props["Properties"]["Handler"]: props["Properties"]
        for props in template.find_resources("AWS::Lambda::Function").values()
        if props["Properties"].get("Runtime", "").startswith("python")
    }


def test_lambdas_run_outside_any_vpc(stacks: dict[str, Template]) -> None:
    for name in ("api", "workers"):
        for handler, props in _functions(stacks[name]).items():
            assert "VpcConfig" not in props, handler


def test_prod_lambdas_read_the_database_secret() -> None:
    built = build(new_app(), get_config("prod"))
    api = _functions(Template.from_stack(built["api"]))
    workers = _functions(Template.from_stack(built["workers"]))
    assert set(workers) == {
        "workers.main.device_message_lambda_handler",
        "workers.main.command_dispatch_lambda_handler",
        "workers.main.job_lambda_handler",
        "workers.main.migrate_lambda_handler",
    }
    for handler, props in {**api, **workers}.items():
        env = props["Environment"]["Variables"]
        assert "DATABASE_SECRET_ARN" in env, handler
        assert env.get("REPOSITORY_BACKEND") == "postgres", handler
        assert "DATABASE_URL" not in env, handler  # never a password in plain env vars
    policies = json.dumps(Template.from_stack(built["workers"]).find_resources("AWS::IAM::Policy"))
    assert "secretsmanager:GetSecretValue" in policies


def test_dev_has_no_database_and_no_migrate_function() -> None:
    built = build(new_app(), get_config("dev"))
    workers = _functions(Template.from_stack(built["workers"]))
    assert "workers.main.migrate_lambda_handler" not in workers
    for props in workers.values():
        assert "DATABASE_SECRET_ARN" not in props["Environment"]["Variables"]


def test_workers_get_their_aws_settings(stacks: dict[str, Template]) -> None:
    workers = _functions(stacks["workers"])
    ingest = workers["workers.main.device_message_lambda_handler"]["Environment"]["Variables"]
    assert "DEVICE_DATA_BUCKET" in ingest
    commands = workers["workers.main.command_dispatch_lambda_handler"]["Environment"]["Variables"]
    assert "IOT_DATA_ENDPOINT" in commands
    policies = json.dumps(stacks["workers"].find_resources("AWS::IAM::Policy"))
    assert "/raw/*" in policies
    assert "/rejected/*" in policies


def test_iot_data_endpoint_is_looked_up_not_hardcoded(stacks: dict[str, Template]) -> None:
    iot = stacks["iot"]
    iot.has_resource_properties(
        "Custom::AWS",
        {"Create": Match.serialized_json(Match.object_like({"action": "describeEndpoint"}))},
    )
    assert "iot:DescribeEndpoint" in json.dumps(iot.find_resources("AWS::IAM::Policy"))


def test_worker_concurrency_is_capped_for_the_database(stacks: dict[str, Template]) -> None:
    mappings = stacks["workers"].find_resources("AWS::Lambda::EventSourceMapping")
    assert len(mappings) == 3
    for mapping in mappings.values():
        assert mapping["Properties"]["ScalingConfig"] == {"MaximumConcurrency": 2}
        assert mapping["Properties"]["FunctionResponseTypes"] == ["ReportBatchItemFailures"]


def test_api_publishes_session_events_and_enqueues(stacks: dict[str, Template]) -> None:
    [api] = _functions(stacks["api"]).values()
    env = api["Environment"]["Variables"]
    for name in ("JOBS_QUEUE_URL", "COMMANDS_QUEUE_URL", "EVENTS_HTTP_DNS"):
        assert name in env
    policies = json.dumps(stacks["api"].find_resources("AWS::IAM::Policy"))
    assert "appsync:EventPublish" in policies
    assert "iot:Publish" not in policies


def test_raw_and_rejected_device_data_expire(stacks: dict[str, Template]) -> None:
    buckets = stacks["storage"].find_resources("AWS::S3::Bucket")
    prefixes = {
        rule.get("Prefix")
        for bucket in buckets.values()
        for rule in bucket["Properties"]["LifecycleConfiguration"]["Rules"]
        if "ExpirationInDays" in rule
    }
    assert {"raw/", "rejected/"} <= prefixes


def test_no_hardcoded_account_ids(stacks: dict[str, Template]) -> None:
    import re

    for template in stacks.values():
        assert not re.search(r"\b\d{12}\b", json.dumps(template.to_json()))


def test_command_dispatcher_can_only_publish_to_command_topics(
    stacks: dict[str, Template],
) -> None:
    policies = json.dumps(stacks["workers"].find_resources("AWS::IAM::Policy"))
    assert "topic/devices/*/commands" in policies
    for channel in ("telemetry", "logs", "status", "events", "responses"):
        assert f"topic/devices/*/{channel}" not in policies


def test_rds_stays_in_free_tier_shape() -> None:
    template = Template.from_stack(build(new_app(), get_config("prod"))["database"])
    template.has_resource_properties(
        "AWS::RDS::DBInstance",
        {
            "DBInstanceClass": "db.t4g.micro",
            "AllocatedStorage": "20",
            "MaxAllocatedStorage": Match.absent(),
        },
    )


def test_user_pool_is_email_password_sign_up_without_mfa(stacks: dict[str, Template]) -> None:
    identity = stacks["identity"]
    identity.has_resource_properties(
        "AWS::Cognito::UserPool",
        {
            "AdminCreateUserConfig": Match.object_like({"AllowAdminCreateUserOnly": False}),
            "UsernameAttributes": ["email"],
            "AutoVerifiedAttributes": ["email"],
            "MfaConfiguration": "OFF",
        },
    )
    identity.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {"GenerateSecret": False, "EnableTokenRevocation": True},
    )


def test_prod_user_pool_has_deletion_protection() -> None:
    template = Template.from_stack(build(cdk.App(), get_config("prod"))["identity"])
    template.has_resource_properties("AWS::Cognito::UserPool", {"DeletionProtection": "ACTIVE"})


def test_api_can_only_list_users_in_its_pool(stacks: dict[str, Template]) -> None:
    api = stacks["api"]
    api.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Environment": {
                "Variables": Match.object_like(
                    {
                        "COGNITO_USER_POOL_ID": Match.any_value(),
                        "COGNITO_APP_CLIENT_ID": Match.any_value(),
                    }
                )
            }
        },
    )
    policies = json.dumps(api.find_resources("AWS::IAM::Policy"))
    assert "cognito-idp:ListUsers" in policies
    assert "cognito-idp:Admin" not in policies


def test_web_bucket_is_private_and_served_through_oac(stacks: dict[str, Template]) -> None:
    web = stacks["web"]
    web.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
    )
    web.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)
    web.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "DefaultCacheBehavior": Match.object_like(
                        {"ViewerProtocolPolicy": "redirect-to-https"}
                    )
                }
            )
        },
    )


def test_web_proxies_api_same_origin_without_caching(stacks: dict[str, Template]) -> None:
    config = next(iter(stacks["web"].find_resources("AWS::CloudFront::Distribution").values()))[
        "Properties"
    ]["DistributionConfig"]
    (api,) = config["CacheBehaviors"]
    assert api["PathPattern"] == "/api/*"
    assert api["CachePolicyId"] == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"  # CachingDisabled
    # AllViewerExceptHostHeader: forwards Authorization, lets API Gateway see its own Host.
    assert api["OriginRequestPolicyId"] == "b689b0a8-53d0-40ab-baf2-68738e2966ac"
    assert "DELETE" in api["AllowedMethods"]
    assert len(api["FunctionAssociations"]) == 1
    # SPA fallback is a function on the site behavior, never distribution-wide error pages
    # (those would replace the API's own 403/404 responses with index.html).
    assert "CustomErrorResponses" not in config


def test_web_domain_only_in_prod() -> None:
    prod = Template.from_stack(build(new_app(), get_config("prod"))["web"])
    prod.has_resource_properties(
        "AWS::CertificateManager::Certificate",
        {"DomainName": "builderwars.jimweaver.com", "ValidationMethod": "DNS"},
    )
    prod.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {"DistributionConfig": Match.object_like({"Aliases": ["builderwars.jimweaver.com"]})},
    )
    dev = Template.from_stack(build(new_app(), get_config("dev"))["web"])
    dev.resource_count_is("AWS::CertificateManager::Certificate", 0)
