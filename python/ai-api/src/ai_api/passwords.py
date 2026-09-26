"""Password hashing with argon2id (OWASP-recommended parameters)."""

from __future__ import annotations

import argon2
from argon2 import exceptions

# RFC 9106 "second recommended" profile: 64 MiB, 3 passes, 4 lanes.
_HASHER = argon2.PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=4)
# Longer inputs are rejected before hashing: argon2 on a megabyte-long
# password is a cheap way to burn the server's CPU.
MAX_PASSWORD_CHARS = 256
# Verified when the username doesn't exist, so a wrong username takes as
# long as a wrong password (no user enumeration by timing).
_DUMMY_HASH = _HASHER.hash("premarket-ai timing equalizer")


def hash_password(password: str) -> str:
    """Hashes a password for storage.

    Args:
        password: The plain-text password.

    Returns:
        The encoded argon2id hash (salt and parameters included).
    """
    return _HASHER.hash(password)


def verify_password(encoded_hash: str | None, password: str) -> bool:
    """Checks a password against a stored hash in constant time.

    Args:
        encoded_hash: The stored hash, or None when the user doesn't exist
            (a dummy hash is checked instead, and the result is False).
        password: The password to check.

    Returns:
        True only if the user exists and the password matches.
    """
    if len(password) > MAX_PASSWORD_CHARS:
        return False
    try:
        matches = _HASHER.verify(
            _DUMMY_HASH if encoded_hash is None else encoded_hash, password
        )
    except (exceptions.VerificationError, exceptions.InvalidHashError):
        return False
    return matches and encoded_hash is not None
