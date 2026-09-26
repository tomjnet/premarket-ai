"""What the scheduler reads and writes in Postgres (as the owner).

It writes only ``ai.schedule_run``. Everything else it reads to decide
what to run next: the ingest run (through ``ai.v_ingest_run``, the
strangler-fig view), and the latest rule, AI and verify runs and briefs of
a feed date.
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any, Protocol

import psycopg
from psycopg import rows


@dataclasses.dataclass(frozen=True)
class VerifyState:
    """The newest verify run of a feed date.

    Attributes:
        status: QUEUED, RUNNING, DONE or FAILED; None when there is none.
        total: Unique items queued.
        done: Items finished.
    """

    status: str | None
    total: int = 0
    done: int = 0

    @property
    def backlog(self) -> int:
        """Items still waiting while the run is queued or running."""
        if self.status not in ("QUEUED", "RUNNING"):
            return 0
        return max(self.total - self.done, 0)


@dataclasses.dataclass(frozen=True)
class BriefState:
    """The newest brief of a feed date and edition that didn't fail.

    Attributes:
        status: QUEUED, RUNNING, DONE or FAILED; None when there is none.
        finished_at: When it was published (UTC).
    """

    status: str | None
    finished_at: datetime.datetime | None = None


class Store(Protocol):
    """The scheduler's database access (a fake in tests)."""

    async def start(self, day: datetime.date, job: str, mode: str) -> int:
        """Inserts a RUNNING row; returns its id."""

    async def finish(self, run_id: int, status: str, detail: str) -> None:
        """Ends a row."""

    async def record(
        self, day: datetime.date, job: str, mode: str, status: str, detail: str
    ) -> None:
        """Inserts a finished row (an SLA check)."""

    async def finished_today(self, day: datetime.date, job: str) -> bool:
        """True when ``job`` has a DONE row for ``day``."""

    async def ingest_status(self, day: datetime.date) -> str | None:
        """The newest ingest run's status."""

    async def run_status(self, table: str, day: datetime.date) -> str | None:
        """The newest ``ai.rule_run`` / ``ai.ai_run`` status."""

    async def verify(self, day: datetime.date) -> VerifyState:
        """The newest verify run."""

    async def brief(self, day: datetime.date, edition: str) -> BriefState:
        """The newest brief of an edition."""


_RUN_TABLES = frozenset({"ai.rule_run", "ai.ai_run"})


class PostgresStore:
    """``Store`` over short owner connections."""

    def __init__(self, dsn: str) -> None:
        """Connects with ``dsn`` for every call (a few calls a minute)."""
        self._dsn = dsn

    async def _one(self, sql: str, params: Any = None) -> dict[str, Any] | None:
        async with await psycopg.AsyncConnection.connect(
            self._dsn, autocommit=True
        ) as conn:
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(sql, params)
            return await cur.fetchone()

    async def start(self, day: datetime.date, job: str, mode: str) -> int:
        """Inserts a RUNNING row; returns its id."""
        row = await self._one(
            "INSERT INTO ai.schedule_run (feed_date, job, run_mode, status)"
            " VALUES (%s, %s, %s, 'RUNNING') RETURNING id",
            (day, job, mode),
        )
        return int(row["id"])

    async def finish(self, run_id: int, status: str, detail: str) -> None:
        """Ends a row."""
        await self._one(
            "UPDATE ai.schedule_run SET status = %s, detail = %s,"
            " finished_at = now() WHERE id = %s RETURNING id",
            (status, detail[:2000], run_id),
        )

    async def record(
        self, day: datetime.date, job: str, mode: str, status: str, detail: str
    ) -> None:
        """Inserts a finished row (an SLA check)."""
        await self._one(
            "INSERT INTO ai.schedule_run (feed_date, job, run_mode, status,"
            " finished_at, detail) VALUES (%s, %s, %s, %s, now(), %s)"
            " RETURNING id",
            (day, job, mode, status, detail[:2000]),
        )

    async def finished_today(self, day: datetime.date, job: str) -> bool:
        """True when ``job`` has a DONE row for ``day``."""
        row = await self._one(
            "SELECT 1 AS found FROM ai.schedule_run WHERE feed_date = %s"
            " AND job = %s AND status = 'DONE' LIMIT 1",
            (day, job),
        )
        return row is not None

    async def ingest_status(self, day: datetime.date) -> str | None:
        """The newest ingest run's status."""
        row = await self._one(
            "SELECT status FROM ai.v_ingest_run WHERE feed_date = %s"
            " ORDER BY started_at DESC, run_id DESC LIMIT 1",
            (day,),
        )
        return None if row is None else row["status"]

    async def run_status(self, table: str, day: datetime.date) -> str | None:
        """The newest ``ai.rule_run`` / ``ai.ai_run`` status.

        Raises:
            ValueError: Another table.
        """
        if table not in _RUN_TABLES:
            raise ValueError(f"not a run table: {table}")
        row = await self._one(
            f"SELECT status FROM {table} WHERE feed_date = %s"
            " ORDER BY started_at DESC LIMIT 1",
            (day,),
        )
        return None if row is None else row["status"]

    async def verify(self, day: datetime.date) -> VerifyState:
        """The newest verify run."""
        row = await self._one(
            "SELECT status, total, done FROM ai.verify_run"
            " WHERE feed_date = %s ORDER BY requested_at DESC LIMIT 1",
            (day,),
        )
        if row is None:
            return VerifyState(None)
        return VerifyState(row["status"], row["total"] or 0, row["done"] or 0)

    async def brief(self, day: datetime.date, edition: str) -> BriefState:
        """The newest brief of an edition that didn't fail."""
        row = await self._one(
            "SELECT status, finished_at FROM ai.brief"
            " WHERE feed_date = %s AND edition = %s"
            " ORDER BY (status <> 'FAILED') DESC, requested_at DESC LIMIT 1",
            (day, edition),
        )
        if row is None:
            return BriefState(None)
        return BriefState(row["status"], row["finished_at"])
