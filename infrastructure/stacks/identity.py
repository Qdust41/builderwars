"""Human identities (Cognito). Device identities are separate: X.509 certs in AWS IoT."""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_cognito as cognito
from config import EnvConfig
from constructs import Construct


class IdentityStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, config: EnvConfig, **kw: Any) -> None:
        super().__init__(scope, cid, **kw)
        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=config.resource_name("users"),
            self_sign_up_enabled=False,  # TODO: sign-up/invite flow (open decision #10)
            sign_in_aliases=cognito.SignInAliases(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True)
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=12, require_digits=True, require_lowercase=True, require_uppercase=True
            ),
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(sms=False, otp=True),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=config.removal_policy,
        )
        # Public SPA client: no secret; authorization-code + PKCE via the hosted UI (TODO domain).
        self.user_pool_client = self.user_pool.add_client(
            "WebClient",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=True),
            prevent_user_existence_errors=True,
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
        )
        CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=self.user_pool_client.user_pool_client_id)
