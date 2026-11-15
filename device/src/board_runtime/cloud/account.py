"""Sign in to a Builderwars account from the CLI and call the API as that user.

Boards have no AWS IoT certificates yet, so the person running the board signs in here with
their own account (email + password, the same as the web app) and the CLI uploads the board's
telemetry and logs on their behalf (``POST /devices/{id}/messages``).

* ``builderwars login`` reads the sign-in settings from the API (``GET /client-config``), then
  signs in to Cognito directly (``USER_PASSWORD_AUTH``). The password goes over TLS to Cognito
  only; it is never sent to the Builderwars API and never written to disk.
* What is kept on disk (``<state-dir>/account.json``, mode 0600) is the API address, the email,
  the refresh token and the current ID token. ``builderwars logout`` deletes it.
* ID tokens last an hour; :class:`CloudSession` refreshes them with the refresh token (30 days)
  when they are about to expire.

A local API (``APP_ENV=local``) answers ``/client-config`` with ``dev-header`` auth; then login
just records a dev user name and requests carry ``X-Dev-User``, so the same commands work
against ``uvicorn`` on a laptop.

Standard library only (Python 3.10+).
"""

from __future__ import annotations

import base64
import json
import os
import stat
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DEFAULT_API_URL = "https://builderwars.jimweaver.com/api"
ACCOUNT_FILE = "account.json"
REQUEST_TIMEOUT_S = 15.0
REFRESH_MARGIN_S = 120  # refresh the ID token this long before it expires

# (method, url, headers, body, timeout) -> (status, response body)
HttpSend = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, bytes]]


class AccountError(Exception):
    """Sign-in or an API call failed; ``hint`` says what the user can do about it."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class NotLoggedInError(AccountError):
    def __init__(self) -> None:
        super().__init__("not signed in", "run `builderwars login` first")


class NewPasswordRequired(AccountError):
    """Cognito wants a new password (accounts created from the console get a temporary one)."""

    def __init__(self, session: str) -> None:
        super().__init__("a new password is required")
        self.session = session


def urllib_send(
    method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> tuple[int, bytes]:
    scheme = urlsplit(url).scheme
    if scheme not in ("https", "http"):
        raise AccountError(f"unsupported URL {url!r}")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return int(response.status), bytes(response.read())
    except urllib.error.HTTPError as exc:
        return int(exc.code), bytes(exc.read())
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise AccountError(f"cannot reach {urlsplit(url).netloc}: {reason}") from exc


def normalize_api_url(url: str) -> str:
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.netloc:
        raise AccountError(
            f"{url!r} is not an API address", f"use e.g. {DEFAULT_API_URL} or http://localhost:8000"
        )
    if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise AccountError("the API address must use https (http is only for localhost)")
    return url


def _jwt_claims(token: str) -> dict[str, Any]:
    """Read a JWT's claims WITHOUT verifying it (the API verifies; this is for display/expiry)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as exc:
        raise AccountError("Cognito returned a malformed token") from exc
    if not isinstance(claims, dict):
        raise AccountError("Cognito returned a malformed token")
    return claims


@dataclass
class Account:
    api_url: str
    auth_mode: str  # "cognito" | "dev-header"
    email: str  # the dev user name in dev-header mode
    cognito_region: str | None = None
    cognito_app_client_id: str | None = None
    refresh_token: str | None = None
    id_token: str | None = None
    id_token_expires_at: float = 0.0

    @classmethod
    def path(cls, state_dir: Path) -> Path:
        return Path(state_dir) / ACCOUNT_FILE

    @classmethod
    def load(cls, state_dir: Path) -> Account:
        path = cls.path(state_dir)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(**data)
        except FileNotFoundError:
            raise NotLoggedInError() from None
        except (OSError, ValueError, TypeError) as exc:
            raise AccountError(
                f"cannot read {path}: {exc}", "run `builderwars login` again"
            ) from exc

    def save(self, state_dir: Path) -> Path:
        path = self.path(state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        # Created 0600 so the refresh token is never readable by other users, even briefly.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(asdict(self), handle, indent=2)
        os.replace(tmp, path)
        return path

    @classmethod
    def forget(cls, state_dir: Path) -> bool:
        try:
            cls.path(state_dir).unlink()
        except FileNotFoundError:
            return False
        return True


class CognitoClient:
    """The two Cognito calls the CLI needs, over plain HTTPS (no AWS credentials involved)."""

    def __init__(self, region: str, client_id: str, *, send: HttpSend = urllib_send) -> None:
        self._url = f"https://cognito-idp.{region}.amazonaws.com/"
        self._client_id = client_id
        self._send = send

    def password_sign_in(self, email: str, password: str) -> dict[str, Any]:
        result = self._call(
            "InitiateAuth",
            {
                "AuthFlow": "USER_PASSWORD_AUTH",
                "ClientId": self._client_id,
                "AuthParameters": {"USERNAME": email, "PASSWORD": password},
            },
        )
        if result.get("ChallengeName") == "NEW_PASSWORD_REQUIRED":
            raise NewPasswordRequired(str(result.get("Session", "")))
        return self._tokens(result)

    def set_new_password(self, email: str, new_password: str, session: str) -> dict[str, Any]:
        result = self._call(
            "RespondToAuthChallenge",
            {
                "ChallengeName": "NEW_PASSWORD_REQUIRED",
                "ClientId": self._client_id,
                "Session": session,
                "ChallengeResponses": {"USERNAME": email, "NEW_PASSWORD": new_password},
            },
        )
        return self._tokens(result)

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        result = self._call(
            "InitiateAuth",
            {
                "AuthFlow": "REFRESH_TOKEN_AUTH",
                "ClientId": self._client_id,
                "AuthParameters": {"REFRESH_TOKEN": refresh_token},
            },
        )
        return self._tokens(result)

    def _tokens(self, result: dict[str, Any]) -> dict[str, Any]:
        if result.get("ChallengeName"):
            raise AccountError(
                f"Cognito asked for {result['ChallengeName']}, which the CLI does not support",
                "sign in once in the web app, then try again",
            )
        tokens = result.get("AuthenticationResult")
        if not isinstance(tokens, dict) or "IdToken" not in tokens:
            raise AccountError("Cognito did not return tokens")
        return tokens

    def _call(self, action: str, body: dict[str, Any]) -> dict[str, Any]:
        status, raw = self._send(
            "POST",
            self._url,
            {
                "Content-Type": "application/x-amz-json-1.1",
                "X-Amz-Target": f"AWSCognitoIdentityProviderService.{action}",
            },
            json.dumps(body).encode(),
            REQUEST_TIMEOUT_S,
        )
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            data = {}
        if status == 200 and isinstance(data, dict):
            return data
        kind = str(data.get("__type", "")).rsplit("#", 1)[-1] if isinstance(data, dict) else ""
        message = data.get("message") if isinstance(data, dict) else None
        raise _cognito_error(kind, message or f"HTTP {status}")


def _cognito_error(kind: str, message: str) -> AccountError:
    if kind == "NotAuthorizedException":
        if "Refresh Token" in message or "refresh token" in message.lower():
            return AccountError("your sign-in has expired", "run `builderwars login` again")
        return AccountError("incorrect email or password", "the same as the web app's sign-in")
    if kind == "UserNotConfirmedException":
        return AccountError(
            "this account's email is not verified yet",
            "finish sign-up in the web app (enter the emailed code), then log in again",
        )
    if kind == "PasswordResetRequiredException":
        return AccountError("a password reset is required", "reset it from the web app")
    if kind == "InvalidPasswordException":
        return AccountError(f"password rejected: {message}")
    if kind == "InvalidParameterException" and "USER_PASSWORD_AUTH" in message:
        return AccountError(
            "this deployment does not allow CLI sign-in yet",
            "the API's Cognito client needs the USER_PASSWORD_AUTH flow (redeploy from main)",
        )
    if kind == "TooManyRequestsException":
        return AccountError("too many sign-in attempts", "wait a minute and try again")
    return AccountError(f"sign-in failed: {kind or 'error'}: {message}")


def fetch_client_config(api_url: str, *, send: HttpSend = urllib_send) -> dict[str, Any]:
    status, raw = send(
        "GET", f"{api_url}/client-config", {"Accept": "application/json"}, None, REQUEST_TIMEOUT_S
    )
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        data = None
    if status != 200 or not isinstance(data, dict) or "auth_mode" not in data:
        raise AccountError(
            f"{api_url} did not answer /client-config (HTTP {status})",
            "check the address (prod: " + DEFAULT_API_URL + "), or deploy the latest API",
        )
    return data


def login(
    *,
    api_url: str,
    email: str,
    password: Callable[[], str],
    new_password: Callable[[], str],
    state_dir: Path,
    send: HttpSend = urllib_send,
    now: Callable[[], float] = time.time,
) -> Account:
    """Sign in and save the account. ``password``/``new_password`` prompt only when needed."""
    api_url = normalize_api_url(api_url)
    config = fetch_client_config(api_url, send=send)
    if config["auth_mode"] == "dev-header":
        account = Account(api_url=api_url, auth_mode="dev-header", email=email)
        account.save(state_dir)
        return account
    if config["auth_mode"] != "cognito":
        raise AccountError(f"unsupported sign-in mode {config['auth_mode']!r}")
    region = config.get("cognito_region")
    client_id = config.get("cognito_app_client_id")
    if not region or not client_id:
        raise AccountError("the API did not say which Cognito user pool to use")
    cognito = CognitoClient(str(region), str(client_id), send=send)
    try:
        tokens = cognito.password_sign_in(email, password())
    except NewPasswordRequired as challenge:
        tokens = cognito.set_new_password(email, new_password(), challenge.session)
    claims = _jwt_claims(tokens["IdToken"])
    account = Account(
        api_url=api_url,
        auth_mode="cognito",
        email=str(claims.get("email") or email),
        cognito_region=str(region),
        cognito_app_client_id=str(client_id),
        refresh_token=tokens.get("RefreshToken"),
        id_token=tokens["IdToken"],
        id_token_expires_at=float(claims.get("exp", now() + 3600)),
    )
    account.save(state_dir)
    return account


class CloudSession:
    """Authenticated JSON calls to the Builderwars API as the signed-in user."""

    def __init__(
        self,
        account: Account,
        state_dir: Path,
        *,
        send: HttpSend = urllib_send,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.account = account
        self._state_dir = Path(state_dir)
        self._send = send
        self._now = now

    @classmethod
    def load(cls, state_dir: Path, *, send: HttpSend = urllib_send) -> CloudSession:
        return cls(Account.load(state_dir), state_dir, send=send)

    def auth_headers(self) -> dict[str, str]:
        account = self.account
        if account.auth_mode == "dev-header":
            return {"X-Dev-User": account.email}
        if not account.id_token or self._now() > account.id_token_expires_at - REFRESH_MARGIN_S:
            self._refresh()
        return {"Authorization": f"Bearer {self.account.id_token}"}

    def _refresh(self) -> None:
        account = self.account
        if not account.refresh_token or not account.cognito_region:
            raise NotLoggedInError()
        assert account.cognito_app_client_id is not None
        cognito = CognitoClient(
            account.cognito_region, account.cognito_app_client_id, send=self._send
        )
        tokens = cognito.refresh(account.refresh_token)
        account.id_token = tokens["IdToken"]
        account.id_token_expires_at = float(
            _jwt_claims(tokens["IdToken"]).get("exp", self._now() + 3600)
        )
        if tokens.get("RefreshToken"):
            account.refresh_token = tokens["RefreshToken"]
        account.save(self._state_dir)

    def request(self, method: str, path: str, body: Any = None) -> Any:
        """Call the API; raise :class:`AccountError` with the API's ``detail`` on failure."""
        data = None if body is None else json.dumps(body).encode()
        for attempt in (1, 2):
            headers = {"Accept": "application/json", **self.auth_headers()}
            if data is not None:
                headers["Content-Type"] = "application/json"
            status, raw = self._send(
                method, f"{self.account.api_url}{path}", headers, data, REQUEST_TIMEOUT_S
            )
            if status == 401 and attempt == 1 and self.account.auth_mode == "cognito":
                self.account.id_token = None  # e.g. revoked or clock skew: refresh once
                continue
            break
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = None
        if 200 <= status < 300:
            return parsed
        detail = parsed.get("detail") if isinstance(parsed, dict) else None
        code = parsed.get("code") if isinstance(parsed, dict) else None
        raise ApiError(
            status,
            detail if isinstance(detail, str) else f"HTTP {status}",
            code=code if isinstance(code, str) else None,
        )


class ApiError(AccountError):
    def __init__(self, status: int, detail: str, *, code: str | None = None) -> None:
        hint = None
        if status == 401:
            hint = "run `builderwars login` again"
        elif status == 404:
            hint = "check the device id (`builderwars devices` lists yours)"
        elif status == 403:
            hint = "ask the project's owner or an admin for the member role"
        super().__init__(f"API error {status}: {detail}", hint)
        self.status = status
        self.detail = detail
        self.code = code  # e.g. "board_in_use", "run_superseded"
