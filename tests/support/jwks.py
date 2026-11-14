"""A throwaway RSA key pair and helpers that mint Cognito-shaped JWTs for tests."""

from __future__ import annotations

import json
import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

REGION = "us-east-1"
POOL_ID = "us-east-1_TESTPOOL"
CLIENT_ID = "test-client-id"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL_ID}"
KID = "test-key-1"


def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


PRIVATE_KEY = _new_key()
OTHER_PRIVATE_KEY = _new_key()  # not in the JWKS


def jwks() -> dict[str, Any]:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE_KEY.public_key()))
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


def mint(
    sub: str = "user-alice",
    *,
    token_use: str = "access",
    key: rsa.RSAPrivateKey | None = None,
    kid: str = KID,
    algorithm: str = "RS256",
    expires_in: int = 3600,
    drop: tuple[str, ...] = (),
    **overrides: Any,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": sub,
        "iss": ISSUER,
        "token_use": token_use,
        "iat": now,
        "exp": now + expires_in,
    }
    if token_use == "access":
        claims["client_id"] = CLIENT_ID
    else:
        claims["aud"] = CLIENT_ID
        claims["email"] = f"{sub}@example.com"
    claims.update(overrides)
    for name in drop:
        claims.pop(name, None)
    signing_key: Any = key or PRIVATE_KEY
    if algorithm.startswith("HS"):
        signing_key = "a-shared-secret-that-is-long-enough-for-hs256"
    return jwt.encode(claims, signing_key, algorithm=algorithm, headers={"kid": kid})
