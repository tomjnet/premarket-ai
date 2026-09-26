"""What the ADMIN pages change (increment 6), besides users.

- Source reputation (``ai.source_reputation``): the domain list the
  ``source_check`` and ``corroboration`` checks read. An admin adds a
  domain or changes its tier, score or note; analysts' overrides to FAKE
  still lower a score by 0.05 (increment 4).
- The cloud switches of the LLM settings page (``llm.switches``).

Every change is audited by the route (``ai.audit_log``).
"""

from __future__ import annotations

import dataclasses
import datetime

from psycopg_pool import AsyncConnectionPool
from redis import asyncio as aioredis

from ai_api.llm import switches

_MAX_SOURCES = 500


@dataclasses.dataclass(frozen=True)
class SourceRow:
    """One domain's reputation.

    Attributes:
        domain: The host name.
        tier: trusted, neutral, low or blocked.
        reputation: 0 to 1.
        note: Why.
        updated_at: Its last change.
    """

    domain: str
    tier: str
    reputation: float
    note: str
    updated_at: datetime.datetime


class PostgresAdmin:
    """Source reputation and the cloud switches (the API's role)."""

    def __init__(
        self, pool: AsyncConnectionPool, redis: aioredis.Redis
    ) -> None:
        """Uses the API's pool and Redis."""
        self._pool = pool
        self._redis = redis

    async def sources(self, query: str = "") -> list[SourceRow]:
        """Domains containing ``query`` (all when empty), by name."""
        async with self._pool.connection() as conn:
            # strpos, not LIKE: the text is literal (no wildcards).
            cur = await conn.execute(
                "SELECT domain, tier, reputation, note, updated_at"
                " FROM ai.source_reputation WHERE strpos(domain, %s) > 0"
                " ORDER BY domain LIMIT %s",
                (query.lower(), _MAX_SOURCES),
            )
            found = await cur.fetchall()
        return [SourceRow(*row) for row in found]

    async def upsert_source(
        self, domain: str, tier: str, reputation: float, note: str
    ) -> SourceRow:
        """Adds a domain or changes it; returns the stored row."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO ai.source_reputation (domain, tier, reputation,"
                " note) VALUES (%s, %s, %s, %s) ON CONFLICT (domain) DO UPDATE"
                " SET tier = EXCLUDED.tier, reputation = EXCLUDED.reputation,"
                " note = EXCLUDED.note, updated_at = now()"
                " RETURNING domain, tier, reputation, note, updated_at",
                (domain, tier, reputation, note),
            )
            row = await cur.fetchone()
        return SourceRow(*row)

    async def cloud_switches(self) -> dict[str, bool]:
        """The switches in effect (Redis)."""
        return await switches.read(self._redis)

    async def set_cloud_switches(
        self, values: dict[str, bool], user: str
    ) -> dict[str, bool]:
        """Stores the switches (Postgres, then Redis)."""
        return await switches.save(self._pool, self._redis, values, user)

    async def restore(self) -> None:
        """Copies the stored switches to Redis (startup)."""
        await switches.restore(self._pool, self._redis)
