"""The news feed, read from the legacy tables (strangler-fig seam).

Increment 1 reads ``legacy.ingest_run`` and ``legacy.vendor_news_raw``
directly, read-only. From increment 2 the same queries move to the views
``ai.v_ingest_run`` / ``ai.v_raw_news``.
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
FROM legacy.ingest_run
WHERE feed_date = %(day)s
ORDER BY started_at DESC, run_id DESC
LIMIT 1
"""

_ITEM_COLUMNS = """
id, vendor_item_id, feed_date, headline, body, source_url, source_domain,
published_at, tickers, synthetic, is_dup, dup_of
"""

_LIST_SQL = f"""
SELECT {_ITEM_COLUMNS}
FROM legacy.vendor_news_raw
WHERE feed_date = %(day)s
  AND (%(ticker)s::text IS NULL OR %(ticker)s::text = ANY (tickers))
  AND (%(dups)s OR NOT is_dup)
  AND (%(pattern)s::text IS NULL
       OR headline ILIKE %(pattern)s OR body ILIKE %(pattern)s)
ORDER BY published_at DESC, id DESC
LIMIT {_MAX_ITEMS}
"""

_DETAIL_SQL = f"""
SELECT {_ITEM_COLUMNS}
FROM legacy.vendor_news_raw
WHERE id = %(id)s
"""


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
    """Reads ingest runs and news items."""

    async def latest_run(self, day: datetime.date) -> dict[str, Any] | None:
        """Returns the latest ingest run of ``day``, or None."""
        ...

    async def items(self, query: NewsQuery) -> list[dict[str, Any]]:
        """Returns the matching items, newest first (with ``body``)."""
        ...

    async def item(self, item_id: int) -> dict[str, Any] | None:
        """Returns one item (with ``body``), or None."""
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
    """NewsStore over the legacy tables."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Uses connections from ``pool``."""
        self._pool = pool

    async def latest_run(self, day: datetime.date) -> dict[str, Any] | None:
        """Returns the latest ingest run of ``day``, or None."""
        async with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(_RUN_SQL, {"day": day})
            return await cur.fetchone()

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
        """Returns one item (with ``body``), or None."""
        async with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(_DETAIL_SQL, {"id": item_id})
            return await cur.fetchone()
