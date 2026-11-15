"""CLI sign-in (Cognito over plain HTTPS) and the cloud transport, with a fake network."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from board_runtime.cloud import Account, AccountError, CloudApiTransport, CloudSession, login
from board_runtime.cloud.account import normalize_api_url
from board_runtime.connectivity import TransportError

API = "https://builderwars.example.com/api"
COGNITO = "https://cognito-idp.us-east-1.amazonaws.com/"


def _jwt(claims: dict[str, Any]) -> str:
    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part(claims)}.sig"


class FakeNet:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], Any]] = []
        self.cognito: list[tuple[int, dict[str, Any]]] = []
        self.api: list[tuple[int, Any]] = []

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
    ) -> tuple[int, bytes]:
        self.calls.append((method, url, headers, json.loads(body) if body else None))
        if url == f"{API}/client-config":
            return 200, json.dumps(
                {
                    "environment": "prod",
                    "auth_mode": "cognito",
                    "cognito_region": "us-east-1",
                    "cognito_user_pool_id": "us-east-1_abc",
                    "cognito_app_client_id": "client123",
                }
            ).encode()
        if url == COGNITO:
            status, data = self.cognito.pop(0)
            return status, json.dumps(data).encode()
        status, data = self.api.pop(0)
        return status, json.dumps(data).encode()


def _tokens(exp: float, email: str = "ada@example.com") -> dict[str, Any]:
    return {
        "AuthenticationResult": {
            "IdToken": _jwt({"sub": "u1", "email": email, "exp": exp}),
            "RefreshToken": "refresh-1",
        }
    }


def _login(net: FakeNet, tmp_path: Path, now: float = 1000.0) -> Account:
    return login(
        api_url=API,
        email="ada@example.com",
        password=lambda: "pw",
        new_password=lambda: "new-pw",
        state_dir=tmp_path,
        send=net,
        now=lambda: now,
    )


def test_login_signs_in_to_cognito_and_saves_only_tokens(tmp_path: Path) -> None:
    net = FakeNet()
    net.cognito.append((200, _tokens(exp=4600)))
    account = _login(net, tmp_path)
    assert (account.email, account.refresh_token) == ("ada@example.com", "refresh-1")

    _, url, headers, body = net.calls[1]
    assert url == COGNITO
    assert headers["X-Amz-Target"] == "AWSCognitoIdentityProviderService.InitiateAuth"
    assert body["AuthFlow"] == "USER_PASSWORD_AUTH"
    assert body["ClientId"] == "client123"
    saved = (tmp_path / "account.json").read_text()
    assert "pw" not in json.loads(saved).values()  # the password is never stored
    assert (tmp_path / "account.json").stat().st_mode & 0o077 == 0


def test_login_sets_a_new_password_when_cognito_asks(tmp_path: Path) -> None:
    net = FakeNet()
    net.cognito += [
        (200, {"ChallengeName": "NEW_PASSWORD_REQUIRED", "Session": "s1"}),
        (200, _tokens(exp=4600)),
    ]
    _login(net, tmp_path)
    challenge = net.calls[2][3]
    assert challenge["ChallengeName"] == "NEW_PASSWORD_REQUIRED"
    assert challenge["ChallengeResponses"]["NEW_PASSWORD"] == "new-pw"
    assert challenge["Session"] == "s1"


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("NotAuthorizedException", "incorrect email or password"),
        ("UserNotConfirmedException", "not verified"),
    ],
)
def test_login_errors_are_explained(tmp_path: Path, kind: str, expected: str) -> None:
    net = FakeNet()
    net.cognito.append((400, {"__type": kind, "message": "nope"}))
    with pytest.raises(AccountError, match=expected):
        _login(net, tmp_path)
    assert not (tmp_path / "account.json").exists()


def test_session_refreshes_an_expiring_token_and_retries_401_once(tmp_path: Path) -> None:
    net = FakeNet()
    net.cognito.append((200, _tokens(exp=1100)))  # expires 100 s after "now"
    _login(net, tmp_path)
    session = CloudSession(Account.load(tmp_path), tmp_path, send=net, now=lambda: 1000.0)

    net.cognito.append((200, {"AuthenticationResult": {"IdToken": _jwt({"exp": 9000})}}))
    net.api.append((200, []))
    assert session.request("GET", "/projects") == []
    refresh = net.calls[-2][3]
    assert refresh["AuthFlow"] == "REFRESH_TOKEN_AUTH"
    assert refresh["AuthParameters"] == {"REFRESH_TOKEN": "refresh-1"}
    assert Account.load(tmp_path).id_token_expires_at == 9000  # saved for the next command

    # A 401 (e.g. a revoked token) refreshes once and retries.
    net.api += [(401, {"detail": "invalid or expired token"}), (200, [1])]
    net.cognito.append((200, {"AuthenticationResult": {"IdToken": _jwt({"exp": 9500})}}))
    assert session.request("GET", "/projects") == [1]


def test_cloud_transport_buffers_on_outages_and_drops_bad_messages(tmp_path: Path) -> None:
    net = FakeNet()
    net.cognito.append((200, _tokens(exp=10_000)))
    _login(net, tmp_path)
    session = CloudSession(Account.load(tmp_path), tmp_path, send=net, now=lambda: 1000.0)
    transport = CloudApiTransport(session, "dev_1")
    transport.connect()
    payload = json.dumps({"message_type": "log"}).encode()

    net.api.append((503, {"detail": "busy"}))
    with pytest.raises(TransportError):  # the runtime keeps it buffered and retries
        transport.publish("devices/dev_1/logs", payload)

    net.api.append((422, {"detail": "bad"}))
    transport.publish("devices/dev_1/logs", payload)  # dropped, not retried forever

    net.api.append((200, {"processed": 1, "duplicate": 0, "rejected": 0, "results": []}))
    transport.publish("devices/dev_1/logs", payload)
    method, url, headers, body = net.calls[-1]
    assert (method, url) == ("POST", f"{API}/devices/dev_1/messages")
    assert headers["Authorization"].startswith("Bearer ")
    assert body == {
        "messages": [{"topic": "devices/dev_1/logs", "payload": {"message_type": "log"}}]
    }


def test_session_without_login_says_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(AccountError) as exc:
        CloudSession.load(tmp_path)
    assert exc.value.hint == "run `builderwars login` first"


@pytest.mark.parametrize("url", ["ftp://x", "http://example.com/api", "builderwars"])
def test_api_url_must_be_https_except_localhost(url: str) -> None:
    with pytest.raises(AccountError):
        normalize_api_url(url)
    assert normalize_api_url("http://localhost:8000/") == "http://localhost:8000"
