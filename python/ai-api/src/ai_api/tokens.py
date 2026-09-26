"""Short-lived JWT access tokens (HS256).

Each token names its session (``sid``). The session lives in Redis, so
logging out ends every access token of that session at once, before it
expires.
"""

from __future__ import annotations

import dataclasses
import secrets
import time

import jwt

ISSUER = "premarket-ai"
AUDIENCE = "premarket-web"
_ALGORITHM = "HS256"
ROLES = ("TRADER", "ANALYST", "ADMIN")


class InvalidTokenError(Exception):
    """The token is missing, malformed, expired or not ours."""


@dataclasses.dataclass(frozen=True)
class Claims:
    """What an access token says about its bearer.

    Attributes:
        username: The user (``sub``).
        role: TRADER, ANALYST or ADMIN.
        session_id: The Redis session the token belongs to (``sid``).
    """

    username: str
    role: str
    session_id: str


def issue(
    claims: Claims, secret: str, ttl_s: int, now: float | None = None
) -> str:
    """Signs an access token.

    Args:
        claims: The bearer's identity.
        secret: The HMAC key.
        ttl_s: Lifetime in seconds.
        now: The issue time (Unix seconds); None means the current time.

    Returns:
        The encoded JWT.
    """
    issued = int(time.time() if now is None else now)
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": claims.username,
        "role": claims.role,
        "sid": claims.session_id,
        "iat": issued,
        "nbf": issued,
        "exp": issued + ttl_s,
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def verify(token: str, secret: str) -> Claims:
    """Checks a token's signature, lifetime, issuer and audience.

    Args:
        token: The encoded JWT.
        secret: The HMAC key.

    Returns:
        The token's claims.

    Raises:
        InvalidTokenError: The token can't be trusted.
    """
    try:
        # Only HS256 is accepted: never "none", never an algorithm the token
        # picks for itself.
        payload = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={
                "require": ["exp", "iat", "nbf", "iss", "aud", "sub", "sid"]
            },
        )
    except jwt.PyJWTError as e:
        raise InvalidTokenError(str(e)) from e
    role = payload.get("role")
    if role not in ROLES:
        raise InvalidTokenError("unknown role")
    return Claims(
        username=str(payload["sub"]),
        role=role,
        session_id=str(payload["sid"]),
    )
