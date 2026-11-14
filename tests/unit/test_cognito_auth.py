from __future__ import annotations

import pytest

from api.auth import CognitoTokenVerifier, InvalidTokenError, StaticKeySource
from tests.support import jwks


@pytest.fixture
def verifier() -> CognitoTokenVerifier:
    return CognitoTokenVerifier(
        issuer=jwks.ISSUER, client_id=jwks.CLIENT_ID, keys=StaticKeySource(jwks.jwks())
    )


def test_accepts_an_access_token(verifier: CognitoTokenVerifier) -> None:
    verified = verifier.verify(jwks.mint("alice"))
    assert (verified.user_id, verified.token_use, verified.email) == ("alice", "access", None)


def test_accepts_an_id_token_and_reads_email(verifier: CognitoTokenVerifier) -> None:
    verified = verifier.verify(jwks.mint("alice", token_use="id"))
    assert (verified.user_id, verified.email) == ("alice", "alice@example.com")


@pytest.mark.parametrize(
    ("token", "reason"),
    [
        (lambda: jwks.mint(expires_in=-60), "expired"),
        (lambda: jwks.mint(iss="https://cognito-idp.us-east-1.amazonaws.com/other"), "issuer"),
        (lambda: jwks.mint(client_id="someone-else"), "access token for another client"),
        (lambda: jwks.mint(token_use="id", aud="someone-else"), "id token for another client"),
        (lambda: jwks.mint(token_use="refresh"), "unsupported token_use"),
        (lambda: jwks.mint(drop=("token_use",)), "missing token_use"),
        (lambda: jwks.mint(drop=("exp",)), "missing exp"),
        (lambda: jwks.mint(sub=""), "empty subject"),
        (lambda: jwks.mint(key=jwks.OTHER_PRIVATE_KEY), "signed by a key not in the JWKS"),
        (lambda: jwks.mint(kid="unknown-kid"), "unknown kid"),
        (lambda: jwks.mint(algorithm="HS256"), "symmetric algorithm"),
        (lambda: "not-a-jwt", "malformed"),
    ],
)
def test_rejects_bad_tokens(verifier: CognitoTokenVerifier, token: object, reason: str) -> None:
    assert callable(token)
    with pytest.raises(InvalidTokenError):
        verifier.verify(token())


def test_rejects_unsigned_token(verifier: CognitoTokenVerifier) -> None:
    good = jwks.mint()
    header, payload, _ = good.split(".")
    import base64
    import json

    none_header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "kid": jwks.KID}).encode()
    ).rstrip(b"=")
    with pytest.raises(InvalidTokenError):
        verifier.verify(f"{none_header.decode()}.{payload}.")
    assert header  # the original header is irrelevant; only the forged one is sent


def test_leeway_allows_small_clock_skew() -> None:
    lenient = CognitoTokenVerifier(
        issuer=jwks.ISSUER,
        client_id=jwks.CLIENT_ID,
        keys=StaticKeySource(jwks.jwks()),
        leeway_s=120,
    )
    assert lenient.verify(jwks.mint(expires_in=-30)).user_id == "user-alice"
