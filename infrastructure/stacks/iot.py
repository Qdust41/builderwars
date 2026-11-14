"""AWS IoT Core: per-device policy and the rule that forwards device messages to SQS.

Provisioning approach (NOT implemented, no certificates are created here):
* One IoT thing per board; thing name == device id used in topics.
* One X.509 certificate per board, created by a privileged provisioning flow (e.g. fleet
  provisioning by claim, or certificates created out-of-band during manufacturing), attached
  to the thing and to ``DevicePolicy``. Private keys never touch our database or git.
* The policy uses ``${iot:Connection.Thing.ThingName}`` so each board can only use its own
  client id and topics — this is what makes the topic a trustworthy identity.
"""

from __future__ import annotations

from typing import Any

from aws_cdk import Aws, CfnOutput, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_iot as iot
from aws_cdk import aws_sqs as sqs
from config import EnvConfig
from constructs import Construct

THING = "${iot:Connection.Thing.ThingName}"
DEVICE_TO_CLOUD = ("telemetry", "logs", "status", "responses")

# Matches workers.handlers.device_message.IncomingDeviceMessage.
INGEST_RULE_SQL = (
    "SELECT topic() AS topic, timestamp() AS received_at_ms, encode(*, 'base64') AS body_b64 "
    "FROM 'devices/+/+' WHERE topic(3) IN ['telemetry', 'logs', 'status', 'responses']"
)


def _arn(resource: str) -> str:
    return f"arn:{Aws.PARTITION}:iot:{Aws.REGION}:{Aws.ACCOUNT_ID}:{resource}"


def device_policy_document() -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "iot:Connect",
                "Resource": _arn(f"client/{THING}"),
                "Condition": {"Bool": {"iot:Connection.Thing.IsAttached": "true"}},
            },
            {
                "Effect": "Allow",
                "Action": "iot:Publish",
                "Resource": [_arn(f"topic/devices/{THING}/{c}") for c in DEVICE_TO_CLOUD],
            },
            {
                "Effect": "Allow",
                "Action": "iot:Subscribe",
                "Resource": _arn(f"topicfilter/devices/{THING}/commands"),
            },
            {
                "Effect": "Allow",
                "Action": "iot:Receive",
                "Resource": _arn(f"topic/devices/{THING}/commands"),
            },
        ],
    }


class IotStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        config: EnvConfig,
        ingest_queue: sqs.IQueue,
        **kw: Any,
    ) -> None:
        super().__init__(scope, cid, **kw)
        policy = iot.CfnPolicy(
            self,
            "DevicePolicy",
            policy_name=config.resource_name("device"),
            policy_document=device_policy_document(),
        )

        rule_role = iam.Role(
            self,
            "IngestRuleRole",
            assumed_by=iam.ServicePrincipal("iot.amazonaws.com"),
            description="Lets the IoT ingest rule send device messages to the ingest queue only",
        )
        ingest_queue.grant_send_messages(rule_role)

        iot.CfnTopicRule(
            self,
            "IngestRule",
            topic_rule_payload=iot.CfnTopicRule.TopicRulePayloadProperty(
                sql=INGEST_RULE_SQL,
                aws_iot_sql_version="2016-03-23",
                rule_disabled=False,
                actions=[
                    iot.CfnTopicRule.ActionProperty(
                        sqs=iot.CfnTopicRule.SqsActionProperty(
                            queue_url=ingest_queue.queue_url,
                            role_arn=rule_role.role_arn,
                            use_base64=False,
                        )
                    )
                ],
                # TODO: error_action -> S3/CloudWatch Logs so rule failures are visible.
            ),
        )
        # TODO: lifecycle events ($aws/events/presence/+/+) -> ingest, for online/offline status.
        CfnOutput(self, "DevicePolicyName", value=policy.ref)
