"""Postgres side of the rule run (as the database owner, like ``init``).

Raw news is read only through ``ai.v_raw_news`` / ``ai.v_ingest_run``.
"""

from __future__ import annotations

from collections.abc import Sequence
import datetime
from typing import Any

import psycopg
from psycopg import rows
from psycopg.types import json as pg_json

from ai_api.rules import checks
from ai_api.rules import engine
from ai_api.rules import registry as registry_lib

_ITEM_COLUMNS = """
n.id, r.feed_date, r.vendor_item_id, r.headline, r.body, r.source_url,
r.source_domain, r.tickers
"""


def _raw_item(row: dict[str, Any]) -> engine.RawItem:
    return engine.RawItem(
        news_id=row["id"],
        feed_date=row["feed_date"],
        vendor_item_id=row["vendor_item_id"],
        headline=row["headline"],
        body=row["body"],
        source_url=row["source_url"],
        source_domain=row["source_domain"],
        tickers=tuple(row["tickers"]),
    )


class RulesRepository:
    """Reads raw news and writes rule results (autocommit connection)."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        """Uses ``conn``; multi-statement writes run in transactions."""
        self._conn = conn

    async def _all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor(row_factory=rows.dict_row)
        await cur.execute(sql, params)
        return await cur.fetchall()

    async def ingest_status(self, day: datetime.date) -> str | None:
        """Status of the latest ingest run of ``day``, or None."""
        found = await self._all(
            "SELECT status FROM ai.v_ingest_run WHERE feed_date = %s"
            " ORDER BY started_at DESC, run_id DESC LIMIT 1",
            (day,),
        )
        return found[0]["status"] if found else None

    async def raw_days(
        self, first: datetime.date, last: datetime.date
    ) -> list[datetime.date]:
        """Feed dates in [first, last] that have raw news, oldest first."""
        found = await self._all(
            "SELECT DISTINCT feed_date FROM ai.v_raw_news"
            " WHERE feed_date BETWEEN %s AND %s ORDER BY feed_date",
            (first, last),
        )
        return [row["feed_date"] for row in found]

    async def checked_days(
        self, first: datetime.date, last: datetime.date
    ) -> set[datetime.date]:
        """Feed dates in [first, last] with a finished rule run."""
        found = await self._all(
            "SELECT DISTINCT feed_date FROM ai.rule_run"
            " WHERE status = 'DONE' AND feed_date BETWEEN %s AND %s",
            (first, last),
        )
        return {row["feed_date"] for row in found}

    async def load_day(self, day: datetime.date) -> list[engine.RawItem]:
        """The day's items, with ``ai.news_item`` ids, in vendor order."""
        await self._conn.execute(
            "INSERT INTO ai.news_item (feed_date, vendor_item_id)"
            " SELECT feed_date, vendor_item_id FROM ai.v_raw_news"
            " WHERE feed_date = %s ON CONFLICT DO NOTHING",
            (day,),
        )
        found = await self._all(
            f"SELECT {_ITEM_COLUMNS} FROM ai.v_raw_news r"
            " JOIN ai.news_item n USING (feed_date, vendor_item_id)"
            " WHERE r.feed_date = %s ORDER BY r.vendor_item_id",
            (day,),
        )
        return [_raw_item(row) for row in found]

    async def unique_items(self, day: datetime.date) -> list[engine.RawItem]:
        """Items of a checked day that aren't duplicates (for re-indexing)."""
        found = await self._all(
            f"SELECT {_ITEM_COLUMNS} FROM ai.v_raw_news r"
            " JOIN ai.news_item n USING (feed_date, vendor_item_id)"
            " JOIN ai.rule_check c ON c.news_id = n.id"
            " LEFT JOIN ai.duplicate_link d ON d.news_id = n.id"
            " WHERE r.feed_date = %s AND d.news_id IS NULL"
            " ORDER BY r.vendor_item_id",
            (day,),
        )
        return [_raw_item(row) for row in found]

    async def start_run(self, day: datetime.date, backend: str) -> int:
        """Inserts a RUNNING ``ai.rule_run`` row and returns its id."""
        found = await self._all(
            "INSERT INTO ai.rule_run (feed_date, rules_version, backend)"
            " VALUES (%s, %s, %s) RETURNING run_id",
            (day, engine.RULES_VERSION, backend),
        )
        return found[0]["run_id"]

    async def finish_run(
        self,
        run_id: int,
        summary: engine.DaySummary,
        registry_tickers: int | None,
        total_ms: int,
    ) -> None:
        """Marks the run DONE with its counts."""
        await self._conn.execute(
            "UPDATE ai.rule_run SET status = 'DONE', finished_at = now(),"
            " items = %s, duplicates = %s, stale = %s, flagged = %s,"
            " by_type = %s, reason_counts = %s, registry_tickers = %s,"
            " total_ms = %s WHERE run_id = %s",
            (
                summary.items,
                summary.duplicates,
                summary.stale,
                summary.flagged,
                pg_json.Jsonb(summary.by_type),
                pg_json.Jsonb(summary.reason_counts),
                registry_tickers,
                total_ms,
                run_id,
            ),
        )

    async def fail_run(self, run_id: int, error: str) -> None:
        """Marks the run FAILED."""
        await self._conn.execute(
            "UPDATE ai.rule_run SET status = 'FAILED', finished_at = now(),"
            " error = %s WHERE run_id = %s",
            (error[:2000], run_id),
        )

    async def save_results(self, results: Sequence[engine.ItemResult]) -> None:
        """Replaces the rule results and duplicate links of these items."""
        ids = [result.item.news_id for result in results]
        checks_rows = [
            (
                result.item.news_id,
                list(result.reason_codes),
                pg_json.Jsonb([e.to_json() for e in result.evidence]),
                engine.RULES_VERSION,
            )
            for result in results
        ]
        links = [
            (
                result.item.news_id,
                result.duplicate.canonical_id,
                result.duplicate.dup_type,
                result.duplicate.level,
                result.duplicate.score,
                result.duplicate.stale,
            )
            for result in results
            if result.duplicate is not None
        ]
        async with self._conn.transaction():
            await self._conn.execute(
                "DELETE FROM ai.duplicate_link WHERE news_id = ANY (%s)",
                (ids,),
            )
            await self._conn.execute(
                "DELETE FROM ai.rule_check WHERE news_id = ANY (%s)", (ids,)
            )
            async with self._conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO ai.rule_check (news_id, reason_codes,"
                    " evidence, rules_version) VALUES (%s, %s, %s, %s)",
                    checks_rows,
                )
                if links:
                    await cur.executemany(
                        "INSERT INTO ai.duplicate_link (news_id, canonical_id,"
                        " dup_type, level, score, stale)"
                        " VALUES (%s, %s, %s, %s, %s, %s)",
                        links,
                    )

    async def registry_refreshed_at(self) -> datetime.datetime | None:
        """When the registry copy was last refreshed, or None if empty."""
        found = await self._all(
            "SELECT max(refreshed_at) AS at FROM ai.ticker_registry"
        )
        return found[0]["at"]

    async def load_registry(self) -> registry_lib.Registry | None:
        """The registry copy, or None when it's empty."""
        found = await self._all(
            "SELECT ticker, cik, title, refreshed_at FROM ai.ticker_registry"
        )
        if not found:
            return None
        return registry_lib.Registry(
            (
                registry_lib.Company(row["ticker"], row["cik"], row["title"])
                for row in found
            ),
            max(row["refreshed_at"] for row in found),
        )

    async def replace_registry(
        self,
        companies: Sequence[registry_lib.Company],
        refreshed_at: datetime.datetime,
    ) -> None:
        """Replaces the registry copy in one transaction."""
        async with self._conn.transaction():
            await self._conn.execute("DELETE FROM ai.ticker_registry")
            async with (
                self._conn.cursor() as cur,
                cur.copy(
                    "COPY ai.ticker_registry (ticker, cik, title,"
                    " refreshed_at) FROM STDIN"
                ) as copy,
            ):
                for company in companies:
                    await copy.write_row(
                        (
                            company.ticker,
                            company.cik,
                            company.title,
                            refreshed_at,
                        )
                    )

    async def seed_reputations(
        self, reputations: Sequence[checks.Reputation]
    ) -> None:
        """Adds seed reputations; existing rows (admin edits) are kept."""
        async with self._conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO ai.source_reputation (domain, tier, reputation,"
                " note) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                [(r.domain, r.tier, r.reputation, r.note) for r in reputations],
            )

    async def load_reputations(self) -> list[checks.Reputation]:
        """Every row of ``ai.source_reputation``."""
        found = await self._all(
            "SELECT domain, tier, reputation, note FROM ai.source_reputation"
        )
        return [
            checks.Reputation(
                row["domain"], row["tier"], row["reputation"], row["note"]
            )
            for row in found
        ]
