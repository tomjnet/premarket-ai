"""Verify runs and the review queue: the API's side (increment 4).

The API role can create a verify run (``POST /runs``), read runs and the
review queue, and record an analyst's decision:

- the review task becomes APPROVED or OVERRIDDEN (only if it is still
  PENDING: two analysts can't both decide it);
- an override is appended to ``ai.eval_example`` (the learning loop's
  labeled examples, never purged) and, when the analyst says FAKE, costs
  the item's source some reputation.

The worker then resumes the item's graph, which stores the final verdict.
``expire`` (as the owner, ``ai-api expire``) closes what is still pending
at the market open.
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any, Protocol

import psycopg
from psycopg import rows
from psycopg_pool import AsyncConnectionPool

# What an override to FAKE costs the item's source (0 to 1 scale).
REPUTATION_PENALTY = 0.05

_QUEUE_SQL = """
SELECT t.id, t.news_id, t.run_id, t.status, t.reasons, t.ai_verdict,
       t.ai_confidence, t.final_verdict, t.impact_score, t.reviewer,
       t.comment, t.created_at, t.decided_at, t.thread_id,
       n.feed_date, n.vendor_item_id,
       r.id AS raw_id, r.headline, r.source_domain, r.tickers,
       v.reason_codes, v.rationale, v.rule_verdict, v.judge_verdict,
       v.impact
FROM ai.review_task t
JOIN ai.news_item n ON n.id = t.news_id
JOIN ai.v_raw_news r USING (feed_date, vendor_item_id)
LEFT JOIN ai.verification v ON v.news_id = t.news_id
WHERE (%(status)s::text IS NULL OR t.status = %(status)s)
  AND (%(day)s::date IS NULL OR n.feed_date = %(day)s)
ORDER BY (t.status = 'PENDING') DESC, t.impact_score DESC, t.created_at, t.id
LIMIT %(limit)s
"""


class ReviewConflictError(RuntimeError):
    """The task is no longer PENDING (someone decided it already)."""


@dataclasses.dataclass(frozen=True)
class Decision:
    """An analyst's decision on a review task.

    Attributes:
        action: ``approve`` or ``override``.
        reviewer: The analyst's username.
        verdict: The new verdict (override only).
        comment: Why (required for an override).
    """

    action: str
    reviewer: str
    verdict: str | None = None
    comment: str = ""

    def resume_value(self) -> dict[str, Any]:
        """What the graph's ``review`` step receives."""
        return {
            "action": self.action,
            "verdict": self.verdict,
            "reviewer": self.reviewer,
            "comment": self.comment,
        }


class VerdictStore(Protocol):
    """Runs and the review queue (see ``PostgresVerdictStore``)."""

    async def create_run(self, day: datetime.date, user: str) -> dict[str, Any]:
        """Inserts a QUEUED run."""
        ...

    async def active_run(self, day: datetime.date) -> dict[str, Any] | None:
        """The day's QUEUED or RUNNING run, or None."""
        ...

    async def runs(
        self, day: datetime.date | None, limit: int
    ) -> list[dict[str, Any]]:
        """The latest runs, newest first."""
        ...

    async def run(self, run_id: int) -> dict[str, Any] | None:
        """One run, or None."""
        ...

    async def queue(
        self, status: str | None, day: datetime.date | None, limit: int
    ) -> list[dict[str, Any]]:
        """Review tasks, pending first, by market impact."""
        ...

    async def task(self, task_id: int) -> dict[str, Any] | None:
        """One review task (queue row), or None."""
        ...

    async def decide(
        self, task_id: int, decision: Decision
    ) -> dict[str, Any] | None:
        """Records a decision; None when there's no such task.

        Raises:
            ReviewConflictError: The task isn't PENDING any more.
        """
        ...


class PostgresVerdictStore:
    """``VerdictStore`` over the API's pool."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Uses autocommit connections from ``pool``."""
        self._pool = pool

    async def _all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(sql, params)
            return await cur.fetchall()

    async def create_run(self, day: datetime.date, user: str) -> dict[str, Any]:
        """Inserts a QUEUED run."""
        found = await self._all(
            "INSERT INTO ai.verify_run (feed_date, requested_by)"
            " VALUES (%s, %s) RETURNING *",
            (day, user),
        )
        return found[0]

    async def active_run(self, day: datetime.date) -> dict[str, Any] | None:
        """The day's QUEUED or RUNNING run, or None."""
        found = await self._all(
            "SELECT * FROM ai.verify_run WHERE feed_date = %s"
            " AND status IN ('QUEUED', 'RUNNING')"
            " ORDER BY requested_at DESC LIMIT 1",
            (day,),
        )
        return found[0] if found else None

    async def runs(
        self, day: datetime.date | None, limit: int
    ) -> list[dict[str, Any]]:
        """The latest runs, newest first."""
        return await self._all(
            "SELECT * FROM ai.verify_run"
            " WHERE %(day)s::date IS NULL OR feed_date = %(day)s"
            " ORDER BY requested_at DESC, run_id DESC LIMIT %(limit)s",
            {"day": day, "limit": limit},
        )

    async def run(self, run_id: int) -> dict[str, Any] | None:
        """One run, or None."""
        found = await self._all(
            "SELECT * FROM ai.verify_run WHERE run_id = %s", (run_id,)
        )
        return found[0] if found else None

    async def queue(
        self, status: str | None, day: datetime.date | None, limit: int
    ) -> list[dict[str, Any]]:
        """Review tasks, pending first, by market impact."""
        return await self._all(
            _QUEUE_SQL, {"status": status, "day": day, "limit": limit}
        )

    async def task(self, task_id: int) -> dict[str, Any] | None:
        """One review task (queue row), or None."""
        sql = _QUEUE_SQL.replace(
            "WHERE (%(status)s", "WHERE t.id = %(id)s AND (%(status)s"
        )
        found = await self._all(
            sql, {"id": task_id, "status": None, "day": None, "limit": 1}
        )
        return found[0] if found else None

    async def decide(
        self, task_id: int, decision: Decision
    ) -> dict[str, Any] | None:
        """Records a decision (see the module docstring)."""
        status = "OVERRIDDEN" if decision.action == "override" else "APPROVED"
        async with self._pool.connection() as conn, conn.transaction():
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(
                "UPDATE ai.review_task SET status = %s,"
                " final_verdict = coalesce(%s::ai.verdict, ai_verdict),"
                " reviewer = %s, comment = %s, decided_at = now()"
                " WHERE id = %s AND status = 'PENDING'"
                " RETURNING id, news_id, ai_verdict, final_verdict",
                (
                    status,
                    decision.verdict if decision.action == "override" else None,
                    decision.reviewer,
                    decision.comment or None,
                    task_id,
                ),
            )
            updated = await cur.fetchone()
            if updated is None:
                await cur.execute(
                    "SELECT status FROM ai.review_task WHERE id = %s",
                    (task_id,),
                )
                if await cur.fetchone() is None:
                    return None
                raise ReviewConflictError(f"review task {task_id} is decided")
            if decision.action == "override":
                await _learn(cur, updated, decision)
        return await self.task(task_id)


async def _learn(
    cur: psycopg.AsyncCursor, task: dict[str, Any], decision: Decision
) -> None:
    """The learning loop: a labeled example, and the source's reputation."""
    await cur.execute(
        "INSERT INTO ai.eval_example (news_id, feed_date, vendor_item_id,"
        " headline, body, source_domain, tickers, label_verdict,"
        " previous_verdict, reason_codes, reviewer, comment)"
        " SELECT n.id, n.feed_date, n.vendor_item_id, r.headline, r.body,"
        " r.source_domain, r.tickers, %s, %s,"
        " coalesce(v.reason_codes, '{}'), %s, %s"
        " FROM ai.news_item n"
        " JOIN ai.v_raw_news r USING (feed_date, vendor_item_id)"
        " LEFT JOIN ai.verification v ON v.news_id = n.id"
        " WHERE n.id = %s",
        (
            decision.verdict,
            task["ai_verdict"],
            decision.reviewer,
            decision.comment,
            task["news_id"],
        ),
    )
    if decision.verdict == "FAKE" and task["ai_verdict"] != "FAKE":
        await cur.execute(
            "UPDATE ai.source_reputation s"
            " SET reputation = greatest(0, s.reputation - %s),"
            " updated_at = now()"
            " FROM ai.news_item n"
            " JOIN ai.v_raw_news r USING (feed_date, vendor_item_id)"
            " WHERE n.id = %s AND s.domain = lower(r.source_domain)",
            (REPUTATION_PENALTY, task["news_id"]),
        )


def expire_pending(
    conn: psycopg.Connection, day: datetime.date
) -> list[dict[str, Any]]:
    """Closes the day's pending reviews at the market open (as the owner).

    Args:
        conn: An owner connection.
        day: The feed date.

    Returns:
        The expired tasks (``run_id``, ``news_id``, ``thread_id``), whose
        graphs the caller resumes with ``{"action": "expire"}``.
    """
    cur = conn.cursor(row_factory=rows.dict_row)
    cur.execute(
        "UPDATE ai.review_task t SET status = 'EXPIRED', decided_at = now(),"
        " final_verdict = t.ai_verdict FROM ai.news_item n"
        " WHERE n.id = t.news_id AND n.feed_date = %s"
        " AND t.status = 'PENDING'"
        " RETURNING t.id, t.run_id, t.news_id, t.thread_id",
        (day,),
    )
    return cur.fetchall()
