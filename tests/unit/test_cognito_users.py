from __future__ import annotations

from typing import Any

from api.cognito_users import CognitoUserDirectory


class FakeCognito:
    def __init__(self, users: list[dict[str, Any]]) -> None:
        self.users = users
        self.filters: list[str] = []

    def list_users(self, *, UserPoolId: str, Filter: str, Limit: int) -> dict[str, Any]:
        self.filters.append(Filter)
        name, _, quoted = Filter.partition(" = ")
        value = quoted.strip('"')
        matches = [
            u
            for u in self.users
            if any(a["Name"] == name and a["Value"] == value for a in u["Attributes"])
        ]
        return {"Users": matches[:Limit]}


def _user(sub: str, email: str, *, enabled: bool = True) -> dict[str, Any]:
    return {
        "Enabled": enabled,
        "Attributes": [{"Name": "sub", "Value": sub}, {"Name": "email", "Value": email}],
    }


def test_finds_users_by_email_and_sub() -> None:
    fake = FakeCognito([_user("sub-1", "bob@example.com")])
    directory = CognitoUserDirectory(user_pool_id="pool", region="us-east-1", client=fake)
    found = directory.find_by_email("  Bob@Example.com ")
    assert found is not None
    assert found.user_id == "sub-1"
    assert directory.get("sub-1") == found
    assert fake.filters[0] == 'email = "bob@example.com"'


def test_disabled_and_missing_users_are_not_found() -> None:
    fake = FakeCognito([_user("sub-2", "old@example.com", enabled=False)])
    directory = CognitoUserDirectory(user_pool_id="pool", region="us-east-1", client=fake)
    assert directory.find_by_email("old@example.com") is None
    assert directory.find_by_email("nobody@example.com") is None


def test_filter_injection_is_refused() -> None:
    fake = FakeCognito([])
    directory = CognitoUserDirectory(user_pool_id="pool", region="us-east-1", client=fake)
    assert directory.find_by_email('x" or email ^= "') is None
    assert fake.filters == []
