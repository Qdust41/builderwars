"""Bearer-token verification for ``AUTH_MODE=cognito``.

The API verifies every token itself (issuer, client, expiry, signature via the user pool JWKS)
even though API Gateway's JWT authorizer also checks it in AWS: the app must be safe if it is
ever reached another way, and tests exercise the same code path as production.

Both Cognito token types are accepted: an access token names the app client in ``client_id``,
an ID token in ``aud``. Either must match ``COGNITO_APP_CLIENT_ID``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import jwt

ALGORITHM = "RS256"  # Cognito signs with RS256 only; never trust the token's own "alg".
REQUIRED_CLAIMS = ("exp", "iat", "iss", "sub", "token_use")
ACCESS_TOKEN = "access"  # noqa: S105 - Cognito token_use value, not a secret
ID_TOKEN = "id"  # noqa: S105


class InvalidTokenError(Exception):
    """The bearer token is missing, malformed, expired, or not from our user pool."""


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    user_id: str  # Cognito ``sub``
    email: str | None  # present on ID tokens only
    token_use: str


class SigningKeySource(Protocol):
    def key_for(self, kid: str) -> Any: ...


class JwksUrlKeySource:
    """Fetches and caches the user pool's public keys; refetches when an unknown kid appears."""

    def __init__(self, url: str, *, timeout_s: int = 5) -> None:
        self._client = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600, timeout=timeout_s)

    def key_for(self, kid: str) -> Any:
        try:
            return self._client.get_signing_key(kid).key
        except jwt.PyJWKClientError as exc:
            raise InvalidTokenError("signing key not found") from exc


class StaticKeySource:
    """A fixed JWKS document, for tests and offline use."""

    def __init__(self, jwks: Mapping[str, Any]) -> None:
        self._keys = {k.key_id: k.key for k in jwt.PyJWKSet.from_dict(dict(jwks)).keys}

    def key_for(self, kid: str) -> Any:
        try:
            return self._keys[kid]
        except KeyError:
            raise InvalidTokenError("signing key not found") from None


class CognitoTokenVerifier:
    def __init__(
        self, *, issuer: str, client_id: str, keys: SigningKeySource, leeway_s: int = 0
    ) -> None:
        self._issuer = issuer
        self._client_id = client_id
        self._keys = keys
        self._leeway_s = leeway_s

    def verify(self, token: str) -> VerifiedToken:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise InvalidTokenError("malformed token") from exc
        kid = header.get("kid")
        if header.get("alg") != ALGORITHM or not isinstance(kid, str):
            raise InvalidTokenError("unexpected token header")
        key = self._keys.key_for(kid)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                issuer=self._issuer,
                leeway=self._leeway_s,
                # Audience is checked below: access tokens carry it as client_id, not aud.
                options={"require": list(REQUIRED_CLAIMS), "verify_aud": False},
            )
        except jwt.InvalidTokenError as exc:
            raise InvalidTokenError(str(exc)) from exc

        token_use = claims["token_use"]
        if token_use == ACCESS_TOKEN:
            audience_ok = claims.get("client_id") == self._client_id
        elif token_use == ID_TOKEN:
            aud = claims.get("aud")
            audience_ok = aud == self._client_id or (
                isinstance(aud, list) and self._client_id in aud
            )
        else:
            raise InvalidTokenError(f"unsupported token_use {token_use!r}")
        if not audience_ok:
            raise InvalidTokenError("token was issued to a different client")

        sub = claims["sub"]
        if not isinstance(sub, str) or not sub:
            raise InvalidTokenError("invalid subject")
        email = claims.get("email") if token_use == ID_TOKEN else None
        return VerifiedToken(
            user_id=sub, email=email if isinstance(email, str) else None, token_use=token_use
        )
