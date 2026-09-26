"""The tool cache and rate limits (Redis, temporary state only).

Every tool answer is cached for its TTL, keyed by the tool and a hash of
its arguments: EDGAR-backed lookups 24 h, web search results 1 h, fetched
pages 1 h, prices 5 minutes. Losing Redis only means fetching again.

The external APIs are rate-limited per minute (a fixed window), so a busy
run can't get the lab blocked by a search engine or by Yahoo.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import contextlib
import hashlib
import json
import time
from typing import Any

from redis import asyncio as aioredis

LOOKUP_TTL_S = 24 * 3600
WEB_TTL_S = 3600
FETCH_TTL_S = 3600
PRICES_TTL_S = 300


class RateLimitedError(RuntimeError):
    """Too many calls to an external service this minute."""


def key(tool: str, arguments: dict[str, Any]) -> str:
    """``mcp:cache:<tool>:<sha256 of the arguments>``."""
    digest = hashlib.sha256(
        json.dumps(arguments, sort_keys=True).encode()
    ).hexdigest()
    return f"mcp:cache:{tool}:{digest}"


class ToolCache:
    """JSON answers in Redis with a TTL."""

    def __init__(self, redis: aioredis.Redis) -> None:
        """Uses ``redis`` (decode_responses=True)."""
        self._redis = redis

    async def cached(
        self,
        tool: str,
        arguments: dict[str, Any],
        ttl_s: int,
        compute: Callable[[], Awaitable[Any]],
    ) -> Any:
        """The cached answer, or ``compute()``'s (then cached).

        Args:
            tool: The tool's name.
            arguments: Its arguments (the cache key).
            ttl_s: How long the answer stays.
            compute: Produces the answer on a miss.

        Returns:
            The answer.
        """
        name = key(tool, arguments)
        try:
            found = await self._redis.get(name)
        except aioredis.RedisError:
            found = None
        if found is not None:
            return json.loads(found)
        answer = await compute()
        with contextlib.suppress(aioredis.RedisError):
            await self._redis.set(name, json.dumps(answer), ex=ttl_s)
        return answer

    async def limit(self, service: str, per_minute: int) -> None:
        """Counts one call to ``service`` in this minute.

        Raises:
            RateLimitedError: The minute's budget is used up.
        """
        window = int(time.time() // 60)
        name = f"mcp:rate:{service}:{window}"
        count = await self._redis.incr(name)
        if count == 1:
            await self._redis.expire(name, 120)
        if count > per_minute:
            raise RateLimitedError(
                f"{service}: more than {per_minute} calls this minute"
            )
