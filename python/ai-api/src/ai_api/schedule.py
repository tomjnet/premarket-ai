"""The scheduler's record of a day (``ai.schedule_run``), for the web app.

``GET /schedule?date=`` (ANALYST, ADMIN) shows the day's jobs and SLA
checks: the "every SLA green" of increment 6's "done when".
"""

from __future__ import annotations

import datetime
from typing import Any, Protocol

from psycopg import rows
from psycopg_pool import AsyncConnectionPool


class ScheduleStore(Protocol):
    """Reads ``ai.schedule_run``."""

    async def runs(self, day: datetime.date) -> list[dict[str, Any]]:
        """The day's rows, oldest first."""


class PostgresSchedule:
    """``ScheduleStore`` over the API's pool."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Uses ``pool``."""
        self._pool = pool

    async def runs(self, day: datetime.date) -> list[dict[str, Any]]:
        """The day's rows, oldest first."""
        async with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(
                "SELECT job, run_mode, status, started_at, finished_at, detail"
                " FROM ai.schedule_run WHERE feed_date = %s"
                " ORDER BY started_at, id",
                (day,),
            )
            return await cur.fetchall()
