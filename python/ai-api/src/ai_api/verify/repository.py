"""Postgres side of the verification (the worker's least-privilege role).

The worker reads the item, its rule and AI results, and writes the
verdict, its evidence and the review task. The run's counters are
advanced in the same transaction as an item's first verdict, so a job
that is retried after a crash never counts twice.
"""

from __future__ import annotations

from collections.abc import Sequence
import dataclasses
import datetime
from typing import Any

import psycopg
from psycopg import rows
from psycopg_pool import AsyncConnectionPool

from ai_api.verify import evidence as ev

_ITEM_SQL = """
SELECT n.id AS news_id, r.feed_date, r.vendor_item_id, r.headline, r.body,
       r.source_url, r.source_domain, r.tickers, r.synthetic,
       coalesce(c.reason_codes, '{}') AS rule_codes,
       coalesce(c.evidence, '[]') AS rule_evidence,
       a.status AS ai_status,
       coalesce(a.reason_codes, '{}') AS ai_codes,
       coalesce(a.evidence, '[]') AS ai_evidence,
       a.summary, a.sentiment,
       coalesce((SELECT json_agg(json_build_object('name', e.name,
                                                   'ticker', e.ticker)
                                 ORDER BY e.seq)
                 FROM ai.entity e WHERE e.news_id = n.id), '[]')
         AS companies,
       coalesce((SELECT array_agg(cl.text ORDER BY cl.seq)
                 FROM ai.claim cl WHERE cl.news_id = n.id), '{}') AS claims
FROM ai.news_item n
JOIN ai.v_raw_news r USING (feed_date, vendor_item_id)
LEFT JOIN ai.rule_check c ON c.news_id = n.id
LEFT JOIN ai.news_ai a ON a.news_id = n.id
WHERE n.id = %s
"""

# Unique after every duplicate level (L0-L2 rules, L3 AI run).
_UNIQUE_SQL = """
SELECT n.id
FROM ai.news_item n
JOIN ai.v_raw_news r USING (feed_date, vendor_item_id)
JOIN ai.rule_check c ON c.news_id = n.id
LEFT JOIN ai.duplicate_link d ON d.news_id = n.id
WHERE n.feed_date = %s AND d.news_id IS NULL
ORDER BY r.vendor_item_id
"""

_VERDICT_COLUMN = {
    "VERIFIED": "verified",
    "UNVERIFIED": "unverified",
    "MISLEADING": "misleading",
    "FAKE": "fake",
}


class NotReadyError(RuntimeError):
    """The day's rule run or AI run isn't DONE."""


@dataclasses.dataclass(frozen=True)
class Verdict:
    """What the graph decided for one item, ready to store.

    Attributes:
        news_id: The item.
        run_id: The verify run.
        thread_id: The graph's checkpoint thread.
        verdict: The AI's verdict.
        confidence: 0 to 1.
        reason_codes: In display order.
        rationale: Why.
        rule_verdict: The rule-based verdict.
        rule_confidence: Its confidence.
        judge_verdict: The judge's verdict, or None.
        judge_confidence: Its confidence, or None.
        judge_model: The alias that judged, or None.
        escalated: The cloud model judged.
        review_reasons: Why it goes to review (empty: it doesn't).
        relevance: The news kind's relevance.
        impact: low, medium or high.
        impact_score: The review order.
        prompt_version: The judge prompt's version.
        evidence: The numbered evidence.
    """

    news_id: int
    run_id: int
    thread_id: str
    verdict: str
    confidence: float
    reason_codes: tuple[str, ...]
    rationale: str
    rule_verdict: str
    rule_confidence: float
    judge_verdict: str | None
    judge_confidence: float | None
    judge_model: str | None
    escalated: bool
    review_reasons: tuple[str, ...]
    relevance: float
    impact: str
    impact_score: float
    prompt_version: str
    evidence: tuple[ev.Evidence, ...]


@dataclasses.dataclass(frozen=True)
class Progress:
    """A run's progress after an item's first verdict.

    Attributes:
        counted: This call counted the item (not a retry).
        done: Items with a verdict (or a failure).
        total: Items queued.
        feed_date: The run's feed date.
    """

    counted: bool
    done: int
    total: int
    feed_date: datetime.date


class VerifyRepository:
    """Reads items and writes verdicts (the worker's pool)."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Uses autocommit connections from ``pool``."""
        self._pool = pool

    async def _all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(sql, params)
            return await cur.fetchall()

    async def load_item(self, news_id: int) -> dict[str, Any] | None:
        """The item with its rule and AI results, or None."""
        found = await self._all(_ITEM_SQL, (news_id,))
        return found[0] if found else None

    async def run(self, run_id: int) -> dict[str, Any] | None:
        """One ``ai.verify_run`` row, or None."""
        found = await self._all(
            "SELECT * FROM ai.verify_run WHERE run_id = %s", (run_id,)
        )
        return found[0] if found else None

    async def start_run(
        self, run_id: int, model: str, prompt_version: str
    ) -> tuple[datetime.date, list[int], list[str]]:
        """Checks the day is ready, clears its old verdicts, lists items.

        Args:
            run_id: A QUEUED run.
            model: The judge's alias.
            prompt_version: The judge prompt's version.

        Returns:
            The feed date, the unique items' ids, and the checkpoint
            threads of the day's previous verdicts (to delete).

        Raises:
            NotReadyError: The day's rule run or AI run isn't DONE.
        """
        run = await self.run(run_id)
        if run is None:
            raise NotReadyError(f"no verify run {run_id}")
        day = run["feed_date"]
        statuses = await self._all(
            "SELECT (SELECT status FROM ai.rule_run WHERE feed_date = %(d)s"
            "        ORDER BY started_at DESC, run_id DESC LIMIT 1) AS rules,"
            "       (SELECT status FROM ai.ai_run WHERE feed_date = %(d)s"
            "        ORDER BY started_at DESC, run_id DESC LIMIT 1) AS ai",
            {"d": day},
        )
        rules_status, ai_status = statuses[0]["rules"], statuses[0]["ai"]
        if rules_status != "DONE" or ai_status != "DONE":
            raise NotReadyError(
                f"{day}: rule run {rules_status or 'missing'}, AI run "
                f"{ai_status or 'missing'}; run `make -C python rules enrich "
                "DATE=...` first"
            )
        async with self._pool.connection() as conn, conn.transaction():
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(
                "SELECT v.thread_id FROM ai.verification v"
                " JOIN ai.news_item n ON n.id = v.news_id"
                " WHERE n.feed_date = %s",
                (day,),
            )
            threads = [row["thread_id"] for row in await cur.fetchall()]
            await cur.execute(
                "DELETE FROM ai.verification v USING ai.news_item n"
                " WHERE n.id = v.news_id AND n.feed_date = %s",
                (day,),
            )
            await cur.execute(
                "DELETE FROM ai.evidence e USING ai.news_item n"
                " WHERE n.id = e.news_id AND n.feed_date = %s",
                (day,),
            )
            await cur.execute(
                "DELETE FROM ai.review_task t USING ai.news_item n"
                " WHERE n.id = t.news_id AND n.feed_date = %s",
                (day,),
            )
            await cur.execute(_UNIQUE_SQL, (day,))
            ids = [row["id"] for row in await cur.fetchall()]
            await cur.execute(
                "UPDATE ai.verify_run SET status = 'RUNNING',"
                " started_at = now(), total = %s, model = %s,"
                " prompt_version = %s WHERE run_id = %s",
                (len(ids), model, prompt_version, run_id),
            )
        return day, ids, threads

    async def fail_run(self, run_id: int, error: str) -> None:
        """Marks the run FAILED."""
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE ai.verify_run SET status = 'FAILED',"
                " finished_at = now(), error = %s,"
                " total_ms = (extract(epoch FROM now() - coalesce(started_at,"
                " requested_at)) * 1000)::bigint WHERE run_id = %s",
                (error[:2000], run_id),
            )

    async def finish_run(self, run_id: int) -> dict[str, Any] | None:
        """Marks a RUNNING run DONE once every item is counted.

        Returns:
            The run's final row, or None when it wasn't finished by this
            call (not done yet, or already finished).
        """
        found = await self._all(
            "UPDATE ai.verify_run SET status = 'DONE', finished_at = now(),"
            " total_ms = (extract(epoch FROM now() - started_at) * 1000)"
            "::bigint WHERE run_id = %s AND status = 'RUNNING'"
            " AND done >= total RETURNING *",
            (run_id,),
        )
        return found[0] if found else None

    async def save(self, verdict: Verdict) -> Progress:
        """Stores a verdict, its evidence and review task; counts the item.

        Args:
            verdict: The graph's decision.

        Returns:
            The run's progress.
        """
        v = verdict
        pending = bool(v.review_reasons)
        async with self._pool.connection() as conn, conn.transaction():
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(
                "INSERT INTO ai.verification (news_id, run_id, status,"
                " verdict, confidence, reason_codes, rationale,"
                " rule_verdict, rule_confidence, judge_verdict,"
                " judge_confidence, judge_model, escalated, review_status,"
                " review_reasons, relevance, impact, impact_score,"
                " thread_id, prompt_version)"
                " VALUES (%(news_id)s, %(run_id)s, %(status)s, %(verdict)s,"
                " %(confidence)s, %(codes)s, %(rationale)s, %(rule_verdict)s,"
                " %(rule_confidence)s, %(judge_verdict)s,"
                " %(judge_confidence)s, %(judge_model)s, %(escalated)s,"
                " %(review_status)s, %(reasons)s, %(relevance)s, %(impact)s,"
                " %(impact_score)s, %(thread_id)s, %(prompt_version)s)"
                " ON CONFLICT (news_id) DO UPDATE SET run_id ="
                " EXCLUDED.run_id, status = EXCLUDED.status, verdict ="
                " EXCLUDED.verdict, confidence = EXCLUDED.confidence,"
                " reason_codes = EXCLUDED.reason_codes, rationale ="
                " EXCLUDED.rationale, rule_verdict = EXCLUDED.rule_verdict,"
                " rule_confidence = EXCLUDED.rule_confidence, judge_verdict ="
                " EXCLUDED.judge_verdict, judge_confidence ="
                " EXCLUDED.judge_confidence, judge_model ="
                " EXCLUDED.judge_model, escalated = EXCLUDED.escalated,"
                " review_status = EXCLUDED.review_status, review_reasons ="
                " EXCLUDED.review_reasons, relevance = EXCLUDED.relevance,"
                " impact = EXCLUDED.impact, impact_score ="
                " EXCLUDED.impact_score, thread_id = EXCLUDED.thread_id,"
                " prompt_version = EXCLUDED.prompt_version, error = NULL,"
                " updated_at = now()"
                " RETURNING (xmax = 0) AS inserted",
                {
                    "news_id": v.news_id,
                    "run_id": v.run_id,
                    "status": "PENDING_REVIEW" if pending else "DONE",
                    "verdict": v.verdict,
                    "confidence": v.confidence,
                    "codes": list(v.reason_codes),
                    "rationale": v.rationale,
                    "rule_verdict": v.rule_verdict,
                    "rule_confidence": v.rule_confidence,
                    "judge_verdict": v.judge_verdict,
                    "judge_confidence": v.judge_confidence,
                    "judge_model": v.judge_model,
                    "escalated": v.escalated,
                    "review_status": "PENDING" if pending else None,
                    "reasons": list(v.review_reasons),
                    "relevance": v.relevance,
                    "impact": v.impact,
                    "impact_score": v.impact_score,
                    "thread_id": v.thread_id,
                    "prompt_version": v.prompt_version,
                },
            )
            inserted = (await cur.fetchone())["inserted"]
            await _replace_evidence(cur, v.news_id, v.evidence)
            if pending:
                await cur.execute(
                    "INSERT INTO ai.review_task (news_id, run_id, reasons,"
                    " ai_verdict, ai_confidence, impact_score, thread_id)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                    " ON CONFLICT (news_id, run_id) DO NOTHING",
                    (
                        v.news_id,
                        v.run_id,
                        list(v.review_reasons),
                        v.verdict,
                        v.confidence,
                        v.impact_score,
                        v.thread_id,
                    ),
                )
            return await _count(
                cur,
                v.run_id,
                inserted,
                verdict=v.verdict,
                pending=pending,
                escalated=v.escalated,
            )

    async def save_failure(
        self, run_id: int, news_id: int, thread_id: str, error: str
    ) -> Progress:
        """Records an item whose graph failed; counts it once."""
        async with self._pool.connection() as conn, conn.transaction():
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(
                "INSERT INTO ai.verification (news_id, run_id, status,"
                " thread_id, prompt_version, error)"
                " VALUES (%s, %s, 'FAILED', %s, '', %s)"
                " ON CONFLICT (news_id) DO NOTHING"
                " RETURNING (xmax = 0) AS inserted",
                (news_id, run_id, thread_id, error[:2000]),
            )
            row = await cur.fetchone()
            return await _count(cur, run_id, row is not None, failed=True)

    async def finish_review(
        self,
        news_id: int,
        status: str,
        verdict: str,
        entry: ev.Evidence,
    ) -> bool:
        """The verdict after review: DONE, with the decision as evidence.

        Args:
            news_id: The item.
            status: APPROVED, OVERRIDDEN or EXPIRED.
            verdict: The final verdict (the analyst's when overridden).
            entry: The review's evidence entry.

        Returns:
            False when the decision was already stored (a retried job).
        """
        async with self._pool.connection() as conn, conn.transaction():
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(
                "UPDATE ai.verification SET status = 'DONE',"
                " review_status = %s, verdict = %s, updated_at = now()"
                " WHERE news_id = %s AND review_status = 'PENDING'",
                (status, verdict, news_id),
            )
            if cur.rowcount == 0:
                return False
            await cur.execute(
                "INSERT INTO ai.evidence (news_id, seq, check_type, code,"
                " message, source) SELECT %s, coalesce(max(seq), 0) + 1,"
                " %s, %s, %s, %s FROM ai.evidence WHERE news_id = %s",
                (
                    news_id,
                    entry.check,
                    entry.code,
                    entry.message,
                    entry.source,
                    news_id,
                ),
            )
            return True


async def _replace_evidence(
    cur: psycopg.AsyncCursor, news_id: int, evidence: Sequence[ev.Evidence]
) -> None:
    await cur.execute("DELETE FROM ai.evidence WHERE news_id = %s", (news_id,))
    await cur.executemany(
        "INSERT INTO ai.evidence (news_id, seq, check_type, code, message,"
        " source, url, title) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        [
            (
                news_id,
                i + 1,
                e.check,
                e.code,
                e.message,
                e.source,
                e.url,
                e.title,
            )
            for i, e in enumerate(evidence)
        ],
    )


async def _count(
    cur: psycopg.AsyncCursor,
    run_id: int,
    counted: bool,
    *,
    verdict: str | None = None,
    pending: bool = False,
    escalated: bool = False,
    failed: bool = False,
) -> Progress:
    if counted:
        column = _VERDICT_COLUMN.get(verdict or "")
        sets = ["done = done + 1"]
        if column is not None:
            sets.append(f"{column} = {column} + 1")
        if pending:
            sets.append("pending_review = pending_review + 1")
        if escalated:
            sets.append("escalated = escalated + 1")
        if failed:
            sets.append("failed = failed + 1")
        await cur.execute(
            f"UPDATE ai.verify_run SET {', '.join(sets)} WHERE run_id = %s"
            " RETURNING done, total, feed_date",
            (run_id,),
        )
    else:
        await cur.execute(
            "SELECT done, total, feed_date FROM ai.verify_run"
            " WHERE run_id = %s",
            (run_id,),
        )
    row = await cur.fetchone()
    return Progress(counted, row["done"], row["total"], row["feed_date"])
