"""Login sessions and login throttling in Redis.

A session is a Redis hash ``session:<sid>`` with the username, role and the
SHA-256 of the current refresh secret. The refresh token the browser holds (in
an httpOnly cookie) is ``<sid>.<secret>``.

- **Rotation:** every refresh replaces the secret. The old one stays usable
  for a few seconds only, and during that window it returns the same new
  token, so two tabs refreshing at once end up with one valid cookie.
- **Reuse detection:** presenting a rotated secret after that window means
  the token was copied; the whole session is deleted.
- **Absolute lifetime:** the session key's TTL is set at login and never
  extended.
- **Revocation:** access tokens carry the sid and are only accepted while
  the session exists, so logout ends them immediately.

Redis holds nothing that can't be lost: losing it logs everyone out.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import secrets

from redis import asyncio as aioredis

_SESSION_KEY = "session:{sid}"
_GRACE_KEY = "session:{sid}:grace:{secret_hash}"
_FAILURES_KEY = "login:failures:{username}"

# KEYS[1] session, KEYS[2] grace key of the presented secret.
# ARGV[1] presented hash, ARGV[2] new hash, ARGV[3] new token, ARGV[4] grace.
# Returns {1} rotated, {2, token} replay within the grace window, {0} no
# session, {-1} reuse detected (session deleted).
_ROTATE_LUA = """
local current = redis.call('HGET', KEYS[1], 'secret')
if not current then return {0} end
if current == ARGV[1] then
  redis.call('HSET', KEYS[1], 'secret', ARGV[2])
  local ttl = redis.call('TTL', KEYS[1])
  local grace = tonumber(ARGV[4])
  if ttl > 0 and ttl < grace then grace = ttl end
  redis.call('SET', KEYS[2], ARGV[3], 'EX', grace)
  return {1}
end
local replay = redis.call('GET', KEYS[2])
if replay then return {2, replay} end
redis.call('DEL', KEYS[1])
return {-1}
"""


class RotateOutcome(enum.Enum):
    """What happened to a presented refresh token."""

    ROTATED = "rotated"
    NO_SESSION = "no_session"
    REUSED = "reused"


@dataclasses.dataclass(frozen=True)
class Session:
    """A live login session.

    Attributes:
        session_id: The sid, also in every access token of the session.
        username: The user.
        role: The role at login time.
    """

    session_id: str
    username: str
    role: str


@dataclasses.dataclass(frozen=True)
class Rotation:
    """The result of presenting a refresh token.

    Attributes:
        outcome: What happened.
        session: The session, when the token was accepted.
        refresh_token: The token to set in the cookie, when accepted.
    """

    outcome: RotateOutcome
    session: Session | None = None
    refresh_token: str | None = None


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _split(refresh_token: str) -> tuple[str, str] | None:
    sid, sep, secret = refresh_token.partition(".")
    if not sep or not sid or not secret or len(refresh_token) > 200:
        return None
    return sid, secret


class SessionStore:
    """Sessions and failed-login counters, kept in Redis."""

    def __init__(
        self,
        redis: aioredis.Redis,
        *,
        ttl_s: int,
        grace_s: int,
        max_failures: int,
        lockout_s: int,
    ) -> None:
        """Wraps a Redis client.

        Args:
            redis: The client (``decode_responses=True``).
            ttl_s: Absolute session lifetime.
            grace_s: Rotation grace window.
            max_failures: Failed logins before a username is locked.
            lockout_s: Failure-counting window and lockout length.
        """
        self._redis = redis
        self._ttl_s = ttl_s
        self._grace_s = grace_s
        self._max_failures = max_failures
        self._lockout_s = lockout_s
        self._rotate = redis.register_script(_ROTATE_LUA)

    async def create(self, username: str, role: str) -> tuple[Session, str]:
        """Starts a session.

        Args:
            username: The user who logged in.
            role: The user's role.

        Returns:
            The session and its first refresh token.
        """
        sid = secrets.token_urlsafe(16)
        secret = secrets.token_urlsafe(32)
        key = _SESSION_KEY.format(sid=sid)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hset(
                key,
                mapping={
                    "username": username,
                    "role": role,
                    "secret": _hash(secret),
                },
            )
            pipe.expire(key, self._ttl_s)
            await pipe.execute()
        return Session(sid, username, role), f"{sid}.{secret}"

    async def rotate(self, refresh_token: str) -> Rotation:
        """Exchanges a refresh token for a new one.

        Args:
            refresh_token: The token from the cookie.

        Returns:
            The outcome; on success the session and the new token.
        """
        parts = _split(refresh_token)
        if parts is None:
            return Rotation(RotateOutcome.NO_SESSION)
        sid, secret = parts
        presented = _hash(secret)
        new_secret = secrets.token_urlsafe(32)
        new_token = f"{sid}.{new_secret}"
        key = _SESSION_KEY.format(sid=sid)
        result = await self._rotate(
            keys=[key, _GRACE_KEY.format(sid=sid, secret_hash=presented)],
            args=[presented, _hash(new_secret), new_token, self._grace_s],
        )
        code = int(result[0])
        if code == 0:
            return Rotation(RotateOutcome.NO_SESSION)
        if code == -1:
            return Rotation(RotateOutcome.REUSED)
        if code == 2:
            new_token = str(result[1])
        data = await self._redis.hgetall(key)
        if not data:
            return Rotation(RotateOutcome.NO_SESSION)
        session = Session(sid, data["username"], data["role"])
        return Rotation(RotateOutcome.ROTATED, session, new_token)

    async def exists(self, session_id: str) -> bool:
        """Tells whether a session is still live (not logged out/expired)."""
        return bool(
            await self._redis.exists(_SESSION_KEY.format(sid=session_id))
        )

    async def revoke(self, session_id: str) -> None:
        """Ends a session and every access token that names it."""
        await self._redis.delete(_SESSION_KEY.format(sid=session_id))

    async def revoke_token(self, refresh_token: str) -> None:
        """Ends the session a refresh token belongs to (logout)."""
        parts = _split(refresh_token)
        if parts is not None:
            await self.revoke(parts[0])

    async def locked_for(self, username: str) -> int:
        """Seconds until a locked username may try again; 0 if not locked."""
        key = _FAILURES_KEY.format(username=username)
        failures = await self._redis.get(key)
        if failures is None or int(failures) < self._max_failures:
            return 0
        return max(int(await self._redis.ttl(key)), 1)

    async def record_failure(self, username: str) -> None:
        """Counts a failed login; the window starts at the first failure."""
        key = _FAILURES_KEY.format(username=username)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, self._lockout_s, nx=True)
            await pipe.execute()

    async def clear_failures(self, username: str) -> None:
        """Forgets failed logins after a successful one."""
        await self._redis.delete(_FAILURES_KEY.format(username=username))
