"""AppSync Events API for session notifications.

Authorisation approach:
* Users connect and subscribe with their Cognito token.
* Only the backend (IAM) may publish; browsers never publish, so they can't forge events or
  send device commands through this channel.
* TODO: an ``onSubscribe`` handler (or Lambda authoriser) that checks the user is a member of
  ``projects/{project_id}``. Until that exists, any signed-in user could subscribe to any
  project channel — do not put this into use with real users before it is added.
* AppSync Events is pub/sub only; it does not give concurrent-editing semantics.
"""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_appsync as appsync
from aws_cdk import aws_cognito as cognito
from config import EnvConfig
from constructs import Construct

USER_POOL = appsync.AppSyncAuthorizationType.USER_POOL
IAM = appsync.AppSyncAuthorizationType.IAM


class RealtimeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        config: EnvConfig,
        user_pool: cognito.IUserPool,
        **kw: Any,
    ) -> None:
        super().__init__(scope, cid, **kw)
        self.events_api = appsync.EventApi(
            self,
            "Events",
            api_name=config.resource_name("events"),
            authorization_config=appsync.EventApiAuthConfig(
                auth_providers=[
                    appsync.AppSyncAuthProvider(
                        authorization_type=USER_POOL,
                        cognito_config=appsync.AppSyncCognitoConfig(user_pool=user_pool),
                    ),
                    appsync.AppSyncAuthProvider(authorization_type=IAM),
                ],
                connection_auth_mode_types=[USER_POOL, IAM],
                default_subscribe_auth_mode_types=[USER_POOL],
                default_publish_auth_mode_types=[IAM],
            ),
        )
        self.events_api.add_channel_namespace("projects")
        CfnOutput(self, "EventsHttpDns", value=self.events_api.http_dns)
        CfnOutput(self, "EventsRealtimeDns", value=self.events_api.realtime_dns)
