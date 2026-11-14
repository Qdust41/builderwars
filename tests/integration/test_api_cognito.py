"""AUTH_MODE=cognito end to end through FastAPI, against a test JWKS (no network, no AWS)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.auth import CognitoTokenVerifier, StaticKeySource
from api.dependencies import build_container
from api.main import create_app
from api.settings import AppEnv, AuthMode, Settings
from application.adapters.memory import InMemoryUserDirectory
from domain.users import User
from tests.support import jwks

pytestmark = pytest.mark.integration


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
        app_env=AppEnv.TEST,
        auth_mode=AuthMode.COGNITO,
        cognito_region=jwks.REGION,
        cognito_user_pool_id=jwks.POOL_ID,
        cognito_app_client_id=jwks.CLIENT_ID,
    )
    users = InMemoryUserDirectory()
    for sub in ("alice", "bob", "vera", "mallory"):
        users.add(User(user_id=sub, email=f"{sub}@example.com"))
    verifier = CognitoTokenVerifier(
        issuer=settings.cognito_issuer,
        client_id=jwks.CLIENT_ID,
        keys=StaticKeySource(jwks.jwks()),
    )
    container = build_container(settings, token_verifier=verifier, users=users)
    return TestClient(create_app(container=container))


def _as(sub: str, **mint_kw: object) -> dict[str, str]:
    return {"Authorization": f"Bearer {jwks.mint(sub, **mint_kw)}"}  # type: ignore[arg-type]


def test_health_needs_no_token(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic YWxpY2U6cGFzcw=="},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer not-a-jwt"},
        {"X-Dev-User": "alice"},  # the dev header means nothing in cognito mode
    ],
)
def test_missing_or_malformed_credentials_get_401(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.get("/projects", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "mint_kw",
    [
        {"expires_in": -60},
        {"client_id": "another-client"},
        {"iss": "https://cognito-idp.us-east-1.amazonaws.com/another-pool"},
        {"key": jwks.OTHER_PRIVATE_KEY},
    ],
)
def test_invalid_tokens_get_401(client: TestClient, mint_kw: dict[str, object]) -> None:
    assert client.get("/projects", headers=_as("alice", **mint_kw)).status_code == 401


def test_sharing_flow_with_401_403_404(client: TestClient) -> None:
    created = client.post("/projects", json={"name": "Rover"}, headers=_as("alice"))
    assert created.status_code == 201
    pid = created.json()["id"]
    assert created.json()["owner_user_id"] == "alice"

    # 404: a signed-in non-member cannot see the project or its members.
    assert client.get(f"/projects/{pid}", headers=_as("mallory")).status_code == 404
    assert client.get(f"/projects/{pid}/members", headers=_as("mallory")).status_code == 404
    assert (
        client.post(
            f"/projects/{pid}/members",
            json={"email": "mallory@example.com"},
            headers=_as("mallory"),
        ).status_code
        == 404
    )

    # The owner adds a viewer by email; ID tokens work as well as access tokens.
    added = client.post(
        f"/projects/{pid}/members",
        json={"email": "vera@example.com", "role": "viewer"},
        headers=_as("alice", token_use="id"),
    )
    assert added.status_code == 201
    assert added.json() | {"created_at": None} == {
        "user_id": "vera",
        "email": "vera@example.com",
        "role": "viewer",
        "created_at": None,
    }
    assert client.get(f"/projects/{pid}", headers=_as("vera")).status_code == 200

    # 403: a member lacking project:manage_members.
    forbidden = client.post(
        f"/projects/{pid}/members", json={"email": "bob@example.com"}, headers=_as("vera")
    )
    assert forbidden.status_code == 403
    assert client.delete(f"/projects/{pid}/members/alice", headers=_as("vera")).status_code == 403

    # Owner cannot be granted; unknown accounts and duplicates are rejected.
    owner_grant = client.post(
        f"/projects/{pid}/members",
        json={"email": "bob@example.com", "role": "owner"},
        headers=_as("alice"),
    )
    assert owner_grant.status_code == 422
    unknown = client.post(
        f"/projects/{pid}/members", json={"email": "ghost@example.com"}, headers=_as("alice")
    )
    assert unknown.status_code == 404
    duplicate = client.post(
        f"/projects/{pid}/members", json={"email": "vera@example.com"}, headers=_as("alice")
    )
    assert duplicate.status_code == 409

    members = client.get(f"/projects/{pid}/members", headers=_as("vera")).json()
    assert [(m["user_id"], m["role"]) for m in members] == [("alice", "owner"), ("vera", "viewer")]

    # Removal takes access away immediately.
    assert client.delete(f"/projects/{pid}/members/vera", headers=_as("alice")).status_code == 204
    assert client.get(f"/projects/{pid}", headers=_as("vera")).status_code == 404
    assert client.delete(f"/projects/{pid}/members/vera", headers=_as("alice")).status_code == 404
