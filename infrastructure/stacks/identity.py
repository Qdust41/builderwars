"""Human identities (Cognito). Device identities are separate: X.509 certs in AWS IoT.

Owner decisions (2026-11-14, #10 and ADR 0005): email + password only, open self sign-up with
an emailed verification code, MFA off for the MVP. A new account sees nothing until a project
owner or admin adds it to a project by email through the API. Accounts can also be created
from the console, which emails a temporary password.

Cognito's built-in email sender allows about 50 emails a day; switch to SES before real users.
"""

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
            self_sign_up_enabled=True,
            user_verification=cognito.UserVerificationConfig(
                email_subject="Your Builderwars verification code",
                email_body="Your Builderwars verification code is {####}.",
                email_style=cognito.VerificationEmailStyle.CODE,
            ),
            sign_in_aliases=cognito.SignInAliases(email=True),
            sign_in_case_sensitive=False,
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            keep_original=cognito.KeepOriginalAttrs(email=True),  # until the new one is verified
            user_invitation=cognito.UserInvitationConfig(
                email_subject="Your Builderwars account",
                email_body=(
                    "An account was created for {username}. Your temporary password is "
                    "{####}. You will be asked to choose a new one when you first sign in."
                ),
            ),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True)
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_digits=True,
                require_lowercase=True,
                require_uppercase=True,
                temp_password_validity=Duration.days(7),
            ),
            mfa=cognito.Mfa.OFF,  # MVP decision; revisit before wider release
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            deletion_protection=config.retain_data,
            removal_policy=config.removal_policy,
        )
        # Public client shared by the web app (SRP) and the builderwars CLI. The CLI signs in
        # with USER_PASSWORD_AUTH: the password goes over TLS to Cognito only, never to our API,
        # and the CLI keeps just the refresh token. One client keeps a single token audience
        # for the API and AppSync (COGNITO_APP_CLIENT_ID).
        self.user_pool_client = self.user_pool.add_client(
            "WebClient",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=True, user_password=True),
            prevent_user_existence_errors=True,
            enable_token_revocation=True,
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
        )
        CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=self.user_pool_client.user_pool_client_id)
