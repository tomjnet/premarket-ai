"""Briefs in Postgres (``ai.brief``): the API's and the worker's side.

- The API (role ``premarket_ai``) queues a brief (``POST /briefs``) and
  reads the current one of a date (``GET /briefs/today``).
- The worker (role ``premarket_worker``) collects the day's verified items,
  and stores the written brief (``agents.brief.Job``).

The current brief of a date is its newest one that didn't fail (a failed
refresh leaves the morning edition in place); only when every brief of the
date failed is the newest failed one shown, with its error.
"""

from __future__ import annotations

import datetime
from typing import Any, Protocol

from psycopg import rows
from psycopg.types import json as pg_json
from psycopg_pool import AsyncConnectionPool

from ai_api import memory as memory_lib
from ai_api.agents import brief as brief_lib
from ai_api.agents import prompts

_META = (
    "brief_id, feed_date, edition, status, requested_by, requested_at,"
    " started_at, finished_at, error"
)

# The day's unique items with a verification (duplicates have none), their
# AI summary, and their primary source when the corroboration check found
# one.
_ITEMS_SQL = """
SELECT n.id AS news_id, n.vendor_item_id, r.headline, r.source_domain,
       r.published_at, r.tickers, v.status, v.verdict::text AS verdict,
       v.confidence, v.review_status, v.impact, v.impact_score,
       a.summary, a.sentiment, f.url AS filing_url, f.title AS filing_title
FROM ai.verification v
JOIN ai.news_item n ON n.id = v.news_id
JOIN ai.v_raw_news r USING (feed_date, vendor_item_id)
LEFT JOIN ai.news_ai a ON a.news_id = n.id
LEFT JOIN LATERAL (
  SELECT e.url, e.title FROM ai.evidence e
  WHERE e.news_id = n.id AND e.source = 'filing' AND e.url IS NOT NULL
  ORDER BY e.seq LIMIT 1
) f ON true
WHERE n.feed_date = %s
"""


class BriefStore(Protocol):
    """The API's reads and writes (``PostgresBriefs``)."""

    async def create(
        self, day: datetime.date, edition: str, user: str
    ) -> dict[str, Any]:
        """Inserts a QUEUED brief."""
        ...

    async def active(self, day: datetime.date) -> dict[str, Any] | None:
        """The date's QUEUED or RUNNING brief, or None."""
        ...

    async def current(self, day: datetime.date) -> dict[str, Any] | None:
        """The date's current brief (see the module docstring), or None."""
        ...

    async def get(self, brief_id: int) -> dict[str, Any] | None:
        """One brief, or None."""
        ...


class PostgresBriefs:
    """``BriefStore`` and the job's ``Repository`` over one pool."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Uses autocommit connections from ``pool``."""
        self._pool = pool

    async def _all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(sql, params)
            if cur.description is None:
                return []
            return await cur.fetchall()

    # --- the API ------------------------------------------------------------

    async def create(
        self, day: datetime.date, edition: str, user: str
    ) -> dict[str, Any]:
        """Inserts a QUEUED brief."""
        found = await self._all(
            "INSERT INTO ai.brief (feed_date, edition, requested_by)"
            " VALUES (%s, %s, %s) RETURNING *",
            (day, edition, user),
        )
        return found[0]

    async def active(self, day: datetime.date) -> dict[str, Any] | None:
        """The date's QUEUED or RUNNING brief, or None."""
        found = await self._all(
            f"SELECT {_META} FROM ai.brief WHERE feed_date = %s"
            " AND status IN ('QUEUED', 'RUNNING')"
            " ORDER BY requested_at DESC LIMIT 1",
            (day,),
        )
        return found[0] if found else None

    async def current(self, day: datetime.date) -> dict[str, Any] | None:
        """The date's current brief, or None."""
        found = await self._all(
            "SELECT * FROM ai.brief WHERE feed_date = %s"
            " ORDER BY (status <> 'FAILED') DESC, requested_at DESC,"
            " brief_id DESC LIMIT 1",
            (day,),
        )
        return found[0] if found else None

    async def get(self, brief_id: int) -> dict[str, Any] | None:
        """One brief, or None."""
        found = await self._all(
            "SELECT * FROM ai.brief WHERE brief_id = %s", (brief_id,)
        )
        return found[0] if found else None

    # --- the worker ---------------------------------------------------------

    async def start(self, brief_id: int) -> dict[str, Any] | None:
        """QUEUED -> RUNNING, with the date's latest DONE verify run."""
        found = await self._all(
            "UPDATE ai.brief b SET status = 'RUNNING', started_at = now(),"
            " verify_run_id = (SELECT run_id FROM ai.verify_run r"
            "   WHERE r.feed_date = b.feed_date AND r.status = 'DONE'"
            "   ORDER BY r.finished_at DESC LIMIT 1)"
            " WHERE brief_id = %s AND status = 'QUEUED'"
            f" RETURNING {_META}",
            (brief_id,),
        )
        return found[0] if found else None

    async def items(self, day: datetime.date) -> list[dict[str, Any]]:
        """The day's verified unique items."""
        return await self._all(_ITEMS_SQL, (day,))

    async def morning_ids(self, day: datetime.date) -> set[int] | None:
        """News ids of the day's latest DONE morning brief, or None."""
        found = await self._all(
            "SELECT content FROM ai.brief WHERE feed_date = %s"
            " AND edition = 'morning' AND status = 'DONE'"
            " ORDER BY finished_at DESC LIMIT 1",
            (day,),
        )
        if not found:
            return None
        return {i["news_id"] for i in found[0]["content"].get("items", [])}

    async def finish(
        self,
        brief_id: int,
        content: dict[str, Any],
        written: brief_lib.Overview,
        total_ms: int,
    ) -> None:
        """Stores the brief (DONE)."""
        counts = content["counts"]
        stored = {**content, "notes": list(written.notes)}
        await self._all(
            "UPDATE ai.brief SET status = 'DONE', finished_at = now(),"
            " overview = %s, overview_source = %s, citations = %s,"
            " content = %s, verified = %s, unconfirmed = %s,"
            " pending_review = %s, excluded = %s, model = %s,"
            " prompt_version = %s, cloud = %s, cost_usd = %s,"
            " total_ms = %s, error = NULL WHERE brief_id = %s",
            (
                written.text,
                written.source,
                list(written.citations),
                pg_json.Jsonb(stored),
                counts["verified"],
                counts["unconfirmed"],
                counts["pending_review"],
                counts["misleading"] + counts["fake"] + counts["failed"],
                written.model,
                prompts.BRIEF_PROMPT_VERSION,
                written.cloud,
                written.cost_usd,
                total_ms,
                brief_id,
            ),
        )

    async def fail(self, brief_id: int, error: str) -> None:
        """Marks the brief FAILED."""
        await self._all(
            "UPDATE ai.brief SET status = 'FAILED', finished_at = now(),"
            " error = %s WHERE brief_id = %s",
            (error, brief_id),
        )


def for_user(
    content: dict[str, Any], watchlist: memory_lib.Watchlist
) -> list[int]:
    """The brief's items on a user's watchlist (their tickers or sectors).

    Args:
        content: The stored content (``agents.brief.compose``).
        watchlist: The user's watchlist.

    Returns:
        Item numbers, in brief order.
    """
    tickers = set(watchlist.tickers)
    sectors = set(watchlist.sectors)
    return [
        item["n"]
        for item in content.get("items", [])
        if tickers & set(item["tickers"]) or item["sector"] in sectors
    ]
