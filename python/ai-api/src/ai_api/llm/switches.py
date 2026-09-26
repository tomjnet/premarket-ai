"""The admin's cloud switches (increment 6 LLM settings page).

Three switches decide whether a task may call a cloud model at all (the
monthly budget still applies on top):

- ``enabled``: the master switch; off keeps everything local.
- ``judge``: escalation of uncertain verdicts (JUDGE_CLOUD_MODEL).
- ``brief``: the brief's overview (BRIEF_MODEL).

They live in ``ai.app_setting`` (key ``llm.cloud``, the source of truth,
audited) and are mirrored to Redis (``llm:cloud:<name>`` = ``on``/``off``),
where every process's ``CloudBudget.allows(task)`` reads them. ai-api
copies the table to Redis at startup, since Redis keeps no data across a
restart. A switch that was never set is on: the environment decides (a task
without a cloud model configured never calls one anyway).

"Ask the News" stays local: its answers are streamed, and the gateway only
reports a call's cost for a whole answer, so a cloud chat couldn't be kept
inside the budget.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from psycopg_pool import AsyncConnectionPool
from redis import asyncio as aioredis

NAMES = ("enabled", "judge", "brief")
SETTING_KEY = "llm.cloud"


def redis_key(name: str) -> str:
    """The Redis key of one switch."""
    return f"llm:cloud:{name}"


async def read(redis: aioredis.Redis) -> dict[str, bool]:
    """The switches (unset ones are on)."""
    values = await redis.mget([redis_key(n) for n in NAMES])
    return {n: v != "off" for n, v in zip(NAMES, values, strict=True)}


async def mirror(redis: aioredis.Redis, values: Mapping[str, bool]) -> None:
    """Writes the switches to Redis (no expiry)."""
    await redis.mset(
        {redis_key(n): "on" if values.get(n, True) else "off" for n in NAMES}
    )


async def load(pool: AsyncConnectionPool) -> dict[str, bool] | None:
    """The switches stored in Postgres, or None when never set."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT value FROM ai.app_setting WHERE key = %s", (SETTING_KEY,)
        )
        row = await cur.fetchone()
    if row is None:
        return None
    stored: dict[str, Any] = row[0]
    return {n: bool(stored.get(n, True)) for n in NAMES}


async def save(
    pool: AsyncConnectionPool,
    redis: aioredis.Redis,
    values: Mapping[str, bool],
    user: str,
) -> dict[str, bool]:
    """Stores the switches (Postgres, then Redis); returns them."""
    clean = {n: bool(values.get(n, True)) for n in NAMES}
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO ai.app_setting (key, value, updated_by)"
            " VALUES (%s, %s::jsonb, %s) ON CONFLICT (key) DO UPDATE"
            " SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by,"
            " updated_at = now()",
            (SETTING_KEY, json.dumps(clean), user),
        )
    await mirror(redis, clean)
    return clean


async def restore(pool: AsyncConnectionPool, redis: aioredis.Redis) -> None:
    """Copies the stored switches to Redis (ai-api startup)."""
    stored = await load(pool)
    if stored is not None:
        await mirror(redis, stored)
