"""Synthesis tests: build templates in memory and check the safety properties. No AWS calls."""

from __future__ import annotations

import json

import aws_cdk as cdk
import pytest
from app import build
from aws_cdk.assertions import Match, Template
from config import get_config


@pytest.fixture(scope="module", params=["dev", "prod"])
def stacks(request: pytest.FixtureRequest) -> dict[str, Template]:
    app = cdk.App()
    built = build(app, get_config(request.param))
    return {name: Template.from_stack(stack) for name, stack in built.items()}


def test_rds_only_when_enabled() -> None:
    assert "database" not in build(cdk.App(), get_config("dev"))
    with pytest.raises(ValueError, match="unknown env"):
        get_config("staging")  # no deployed staging for the MVP (decision #12)
    assert "database" in build(cdk.App(), get_config("prod"))


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


def test_database_is_private_and_encrypted() -> None:
    template = Template.from_stack(build(cdk.App(), get_config("prod"))["database"])
    template.has_resource_properties(
        "AWS::RDS::DBInstance",
        {"PubliclyAccessible": False, "StorageEncrypted": True, "DeletionProtection": True},
    )


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
    template = Template.from_stack(build(cdk.App(), get_config("prod"))["database"])
    template.has_resource_properties(
        "AWS::RDS::DBInstance",
        {
            "DBInstanceClass": "db.t4g.micro",
            "AllocatedStorage": "20",
            "MaxAllocatedStorage": Match.absent(),
        },
    )
