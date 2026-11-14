"""``UserDirectory`` backed by the Cognito user pool (boto3 ``cognito-idp``).

Needs ``cognito-idp:ListUsers`` on the pool. Lookups use ListUsers filters, which Cognito
supports on ``email`` and ``sub``; both are exact matches.
"""

from __future__ import annotations

from typing import Any

import boto3

from domain.users import User, normalize_email


class CognitoUserDirectory:
    def __init__(self, *, user_pool_id: str, region: str, client: Any | None = None) -> None:
        self._pool = user_pool_id
        self._client = client or boto3.client("cognito-idp", region_name=region)

    def find_by_email(self, email: str) -> User | None:
        return self._find("email", normalize_email(email))

    def get(self, user_id: str) -> User | None:
        return self._find("sub", user_id)

    def _find(self, attribute: str, value: str) -> User | None:
        if '"' in value or "\\" in value:  # would break out of the filter expression
            return None
        response = self._client.list_users(
            UserPoolId=self._pool, Filter=f'{attribute} = "{value}"', Limit=2
        )
        for raw in response.get("Users", []):
            if not raw.get("Enabled", True):
                continue
            attrs = {a["Name"]: a["Value"] for a in raw.get("Attributes", [])}
            if "sub" in attrs and "email" in attrs:
                return User(user_id=attrs["sub"], email=attrs["email"])
        return None
