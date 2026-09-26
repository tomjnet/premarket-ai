"""A token bucket in Redis, shared by every process that calls an API.

SEC EDGAR asks for at most 10 requests per second per client; every EDGAR
call goes through ``TokenBucket("edgar", rate=10)``. The bucket is one
Redis hash updated by a Lua script, so concurrent callers can't overdraw it.
"""

from __future__ import annotations

import asyncio
import math
import time

from redis import asyncio as aioredis

# KEYS[1] bucket. ARGV[1] tokens/s, ARGV[2] burst, ARGV[3] now (ms).
# Takes one token and returns 0, or returns the milliseconds to wait.
_TAKE_LUA = """
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil or ts == nil then
  tokens = burst
  ts = now
end
if now > ts then
  tokens = math.min(burst, tokens + (now - ts) * rate / 1000)
end
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
else
  wait = math.ceil((1 - tokens) * 1000 / rate)
end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('PEXPIRE', KEYS[1], math.ceil(burst * 1000 / rate) + 1000)
return wait
"""


class RateLimitTimeoutError(RuntimeError):
    """No token became free within the caller's deadline."""


class TokenBucket:
    """Up to ``rate`` calls per second, with bursts of ``burst``."""

    def __init__(
        self,
        redis: aioredis.Redis,
        name: str,
        rate: float,
        burst: int | None = None,
    ) -> None:
        """A bucket stored under ``ratelimit:{name}``.

        Args:
            redis: The Redis client.
            name: The API's name, for example ``edgar``.
            rate: Tokens added per second.
            burst: Bucket size; None means ``rate`` rounded up.
        """
        if rate <= 0:
            raise ValueError("rate must be positive")
        self._redis = redis
        self._key = f"ratelimit:{name}"
        self._rate = rate
        self._burst = math.ceil(rate) if burst is None else burst

    async def try_take(self) -> float:
        """Takes a token if one is free.

        Returns:
            0 when a token was taken, else the seconds until one is free.
        """
        now_ms = int(time.time() * 1000)
        wait_ms = await self._redis.eval(
            _TAKE_LUA, 1, self._key, self._rate, self._burst, now_ms
        )
        return int(wait_ms) / 1000

    async def acquire(self, timeout_s: float = 30.0) -> None:
        """Waits for a token.

        Args:
            timeout_s: The longest wait.

        Raises:
            RateLimitTimeoutError: No token within ``timeout_s``.
        """
        deadline = time.monotonic() + timeout_s
        while True:
            wait = await self.try_take()
            if wait == 0:
                return
            if time.monotonic() + wait > deadline:
                raise RateLimitTimeoutError(f"{self._key}: no token in time")
            await asyncio.sleep(wait)
