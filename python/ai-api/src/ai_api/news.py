"""The news feed: raw news through the ``ai.v_*`` views, plus rule results.

From increment 2 the API reads raw news only through ``ai.v_raw_news`` and
``ai.v_ingest_run`` (the strangler-fig seam; they switch from ``legacy.*`` to
``ingest.*`` in increment 6), joined with the rule engine's results.

Duplicates: once the rules have checked an item, ``is_dup`` / ``dup_of``
come from the rule engine (URL, exact and near copies, also of earlier
days). Before that, they're the legacy exact-hash flags.
"""

from __future__ import annotations

import dataclasses
import datetime
import re
from typing import Any, Protocol

from psycopg import rows
from psycopg_pool import AsyncConnectionPool

EXCERPT_MAX_CHARS = 280
# A day is about 100 items; this only guards against a runaway feed.
_MAX_ITEMS = 1000
_WHITESPACE = re.compile(r"\s+")

_RUN_SQL = """
SELECT run_id, status, started_at, finished_at, rows_received, dups
FROM ai.v_ingest_run
WHERE feed_date = %(day)s
ORDER BY started_at DESC, run_id DESC
LIMIT 1
"""

_RULE_RUN_SQL = """
SELECT status, finished_at, items, duplicates, flagged
FROM ai.rule_run
WHERE feed_date = %(day)s
ORDER BY started_at DESC, run_id DESC
LIMIT 1
"""

# One row per raw item, with the rule results when the rules have run.
_ITEMS_CTE = """
WITH items AS (
  SELECT r.id, r.vendor_item_id, r.feed_date, r.headline, r.body,
         r.source_url, r.source_domain, r.published_at, r.tickers,
         r.synthetic,
         (c.news_id IS NOT NULL) AS rules_checked,
         CASE WHEN c.news_id IS NULL THEN r.is_dup
              ELSE d.news_id IS NOT NULL END AS is_dup,
         CASE WHEN c.news_id IS NULL THEN r.dup_of
              ELSE o.vendor_item_id END AS dup_of,
         d.dup_type,
         coalesce(c.reason_codes, '{}') AS reason_codes,
         c.evidence,
         -- Copies in the same feed (a later day's stale copy isn't here).
         (SELECT count(*) FROM ai.duplicate_link x
          JOIN ai.news_item xn ON xn.id = x.news_id
          WHERE x.canonical_id = n.id
            AND xn.feed_date = n.feed_date) AS copies
  FROM ai.v_raw_news r
  LEFT JOIN ai.news_item n
    ON n.feed_date = r.feed_date AND n.vendor_item_id = r.vendor_item_id
  LEFT JOIN ai.rule_check c ON c.news_id = n.id
  LEFT JOIN ai.duplicate_link d ON d.news_id = n.id
  LEFT JOIN ai.news_item o ON o.id = d.canonical_id
  WHERE {where}
)
"""

_LIST_SQL = (
    _ITEMS_CTE.replace("{where}", "r.feed_date = %(day)s")
    + f"""
SELECT * FROM items
WHERE (%(ticker)s::text IS NULL OR %(ticker)s::text = ANY (tickers))
  AND (%(dups)s OR NOT is_dup)
  AND (%(pattern)s::text IS NULL
       OR headline ILIKE %(pattern)s OR body ILIKE %(pattern)s)
ORDER BY published_at DESC, id DESC
LIMIT {_MAX_ITEMS}
"""
)

_DETAIL_SQL = (
    _ITEMS_CTE.replace("{where}", "r.id = %(id)s") + "SELECT * FROM items"
)


@dataclasses.dataclass(frozen=True)
class NewsQuery:
    """Filters of ``GET /news``.

    Attributes:
        day: The feed date.
        ticker: Only items tagged with this ticker (upper case).
        text: Case-insensitive substring of the headline or body.
        include_duplicates: Also return items flagged as duplicates.
    """

    day: datetime.date
    ticker: str | None = None
    text: str | None = None
    include_duplicates: bool = False


class NewsStore(Protocol):
    """Reads ingest runs, rule runs and news items."""

    async def latest_run(self, day: datetime.date) -> dict[str, Any] | None:
        """Returns the latest ingest run of ``day``, or None."""
        ...

    async def latest_rule_run(
        self, day: datetime.date
    ) -> dict[str, Any] | None:
        """Returns the latest rule run of ``day``, or None."""
        ...

    async def items(self, query: NewsQuery) -> list[dict[str, Any]]:
        """Returns the matching items, newest first (with ``body``)."""
        ...

    async def item(self, item_id: int) -> dict[str, Any] | None:
        """Returns one item (with ``body`` and ``evidence``), or None."""
        ...


def like_pattern(text: str) -> str:
    r"""Turns user text into an ILIKE pattern that matches it literally.

    Args:
        text: The search text.

    Returns:
        ``%text%`` with ``\``, ``%`` and ``_`` escaped.
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def excerpt(body: str) -> str:
    """The first characters of a body, as one line of plain text.

    Args:
        body: The full body (untrusted vendor text; returned as text, never
            interpreted).

    Returns:
        At most 280 characters (code points, like Python's ``len``), with
        whitespace collapsed and an ellipsis when cut.
    """
    text = _WHITESPACE.sub(" ", body).strip()
    if len(text) <= EXCERPT_MAX_CHARS:
        return text
    return text[: EXCERPT_MAX_CHARS - 1].rstrip() + "…"


class PostgresNewsStore:
    """NewsStore over the ``ai`` views and rule tables."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Uses connections from ``pool``."""
        self._pool = pool

    async def _one(
        self, sql: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(sql, params)
            return await cur.fetchone()

    async def latest_run(self, day: datetime.date) -> dict[str, Any] | None:
        """Returns the latest ingest run of ``day``, or None."""
        return await self._one(_RUN_SQL, {"day": day})

    async def latest_rule_run(
        self, day: datetime.date
    ) -> dict[str, Any] | None:
        """Returns the latest rule run of ``day``, or None."""
        return await self._one(_RULE_RUN_SQL, {"day": day})

    async def items(self, query: NewsQuery) -> list[dict[str, Any]]:
        """Returns the matching items, newest first (with ``body``)."""
        params = {
            "day": query.day,
            "ticker": query.ticker,
            "dups": query.include_duplicates,
            "pattern": None if query.text is None else like_pattern(query.text),
        }
        async with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(_LIST_SQL, params)
            return await cur.fetchall()

    async def item(self, item_id: int) -> dict[str, Any] | None:
        """Returns one item (with ``body`` and ``evidence``), or None."""
        return await self._one(_DETAIL_SQL, {"id": item_id})
