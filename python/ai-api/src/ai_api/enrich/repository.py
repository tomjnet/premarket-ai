"""Postgres side of the AI run (as the database owner, like the rules)."""

from __future__ import annotations

from collections.abc import Sequence
import dataclasses
import datetime
from typing import Any

import psycopg
from psycopg import rows
from psycopg.types import json as pg_json

from ai_api.dedup import service
from ai_api.enrich import chains
from ai_api.enrich import models
from ai_api.rules import checks


@dataclasses.dataclass
class Outcome:
    """What the AI run decided for one unique item.

    Attributes:
        news_id: The ``ai.news_item`` id.
        status: DONE, SKIPPED, DUPLICATE or FAILED.
        reason_codes: INJECTION_ATTEMPT, UNSUPPORTED_LANGUAGE, STALE.
        evidence: Why, one entry per finding.
        duplicate: The L3 match of a paraphrase.
        extraction: Companies and claims.
        summary: The summary and sentiment.
        error: Why the model call failed.
        conflict: A same-day version with other facts exists (evidence
            only).
    """

    news_id: int
    status: str = "DONE"
    reason_codes: list[str] = dataclasses.field(default_factory=list)
    evidence: list[checks.Evidence] = dataclasses.field(default_factory=list)
    duplicate: service.DedupMatch | None = None
    extraction: models.Extraction | None = None
    summary: chains.SummaryResult | None = None
    error: str | None = None
    conflict: bool = False


@dataclasses.dataclass(frozen=True)
class RunCounts:
    """Counts of one AI run (``ai.ai_run``)."""

    items: int
    paraphrases: int
    conflicts: int
    injections: int
    summarized: int
    fallbacks: int
    skipped: int
    failed: int

    @classmethod
    def of(cls, outcomes: Sequence[Outcome]) -> RunCounts:
        """Counts ``outcomes``."""

        def count(test: Any) -> int:
            return sum(1 for o in outcomes if test(o))

        return cls(
            items=len(outcomes),
            paraphrases=count(lambda o: o.status == "DUPLICATE"),
            conflicts=count(lambda o: o.conflict),
            injections=count(lambda o: "INJECTION_ATTEMPT" in o.reason_codes),
            summarized=count(lambda o: o.summary is not None),
            fallbacks=count(
                lambda o: o.summary is not None
                and o.summary.source == "fallback"
            ),
            skipped=count(lambda o: o.status == "SKIPPED"),
            failed=count(lambda o: o.status == "FAILED"),
        )

    def line(self) -> str:
        """``71 unique -> 3 paraphrases, 68 summarized (0 fallback)...``."""
        return (
            f"{self.items} unique -> {self.paraphrases} paraphrases (L3), "
            f"{self.summarized} summarized ({self.fallbacks} fallback), "
            f"{self.conflicts} conflicting, {self.injections} injection, "
            f"{self.skipped} skipped, {self.failed} failed"
        )


class EnrichRepository:
    """Reads embeddings and writes AI results (autocommit connection)."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        """Uses ``conn``; multi-statement writes run in transactions."""
        self._conn = conn

    async def _all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor(row_factory=rows.dict_row)
        await cur.execute(sql, params)
        return await cur.fetchall()

    async def rule_status(self, day: datetime.date) -> str | None:
        """Status of the latest rule run of ``day``, or None."""
        found = await self._all(
            "SELECT status FROM ai.rule_run WHERE feed_date = %s"
            " ORDER BY started_at DESC, run_id DESC LIMIT 1",
            (day,),
        )
        return found[0]["status"] if found else None

    async def delete_l3_links(self, day: datetime.date) -> None:
        """Removes ``day``'s paraphrase links before checking it again."""
        await self._conn.execute(
            "DELETE FROM ai.duplicate_link d USING ai.news_item n"
            " WHERE n.id = d.news_id AND n.feed_date = %s AND d.level = 'L3'",
            (day,),
        )

    async def embeddings(
        self, keys: dict[int, str], model: str
    ) -> dict[int, list[float]]:
        """Stored embeddings of these items, by the same model and text.

        Args:
            keys: news id -> SHA-256 of the embedded text.
            model: The embedding model alias.

        Returns:
            news id -> embedding, for the ids whose text didn't change.
        """
        if not keys:
            return {}
        found = await self._all(
            "SELECT news_id, text_sha256, embedding FROM ai.news_embedding"
            " WHERE news_id = ANY (%s) AND model = %s",
            (list(keys), model),
        )
        return {
            row["news_id"]: list(row["embedding"])
            for row in found
            if keys.get(row["news_id"]) == row["text_sha256"]
        }

    async def save_embeddings(
        self, records: Sequence[tuple[int, str, str, list[float]]]
    ) -> None:
        """Stores (news id, model, text SHA-256, embedding) rows."""
        async with self._conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO ai.news_embedding (news_id, model, dims,"
                " text_sha256, embedding) VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT (news_id) DO UPDATE SET model = EXCLUDED.model,"
                " dims = EXCLUDED.dims, text_sha256 = EXCLUDED.text_sha256,"
                " embedding = EXCLUDED.embedding, created_at = now()",
                [
                    (news_id, model, len(vector), digest, vector)
                    for news_id, model, digest, vector in records
                ],
            )

    async def start_run(
        self,
        day: datetime.date,
        model: str,
        embed_model: str,
        prompt_version: str,
    ) -> int:
        """Inserts a RUNNING ``ai.ai_run`` row and returns its id."""
        found = await self._all(
            "INSERT INTO ai.ai_run (feed_date, model, embed_model,"
            " prompt_version) VALUES (%s, %s, %s, %s) RETURNING run_id",
            (day, model, embed_model, prompt_version),
        )
        return found[0]["run_id"]

    async def finish_run(
        self, run_id: int, counts: RunCounts, llm_ms: int, total_ms: int
    ) -> None:
        """Marks the run DONE with its counts."""
        await self._conn.execute(
            "UPDATE ai.ai_run SET status = 'DONE', finished_at = now(),"
            " items = %s, paraphrases = %s, conflicts = %s, injections = %s,"
            " summarized = %s, fallbacks = %s, skipped = %s, failed = %s,"
            " llm_ms = %s, total_ms = %s WHERE run_id = %s",
            (
                counts.items,
                counts.paraphrases,
                counts.conflicts,
                counts.injections,
                counts.summarized,
                counts.fallbacks,
                counts.skipped,
                counts.failed,
                llm_ms,
                total_ms,
                run_id,
            ),
        )

    async def fail_run(self, run_id: int, error: str) -> None:
        """Marks the run FAILED."""
        await self._conn.execute(
            "UPDATE ai.ai_run SET status = 'FAILED', finished_at = now(),"
            " error = %s WHERE run_id = %s",
            (error[:2000], run_id),
        )

    async def save_outcomes(
        self,
        run_id: int,
        outcomes: Sequence[Outcome],
        model: str,
        prompt_version: str,
    ) -> None:
        """Replaces the AI results of these items, and adds L3 links."""
        ids = [o.news_id for o in outcomes]
        results = []
        entities = []
        claims = []
        links = []
        for o in outcomes:
            summary = o.summary
            results.append(
                (
                    o.news_id,
                    run_id,
                    o.status,
                    o.reason_codes,
                    pg_json.Jsonb([e.to_json() for e in o.evidence]),
                    None if summary is None else summary.summary,
                    None if summary is None else summary.sentiment,
                    None if summary is None else summary.source,
                    model,
                    prompt_version,
                    o.error,
                )
            )
            if o.extraction is not None:
                entities += [
                    (o.news_id, i, c.name, c.ticker)
                    for i, c in enumerate(o.extraction.companies)
                ]
                claims += [
                    (o.news_id, i, text)
                    for i, text in enumerate(o.extraction.claims)
                ]
            if o.duplicate is not None:
                d = o.duplicate
                links.append(
                    (
                        o.news_id,
                        d.canonical_id,
                        d.dup_type,
                        d.level,
                        d.score,
                        d.stale,
                    )
                )
        async with self._conn.transaction():
            for table in ("news_ai", "entity", "claim"):
                await self._conn.execute(
                    f"DELETE FROM ai.{table} WHERE news_id = ANY (%s)", (ids,)
                )
            async with self._conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO ai.news_ai (news_id, run_id, status,"
                    " reason_codes, evidence, summary, sentiment,"
                    " summary_source, model, prompt_version, error)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    results,
                )
                if entities:
                    await cur.executemany(
                        "INSERT INTO ai.entity (news_id, seq, name, ticker)"
                        " VALUES (%s, %s, %s, %s)",
                        entities,
                    )
                if claims:
                    await cur.executemany(
                        "INSERT INTO ai.claim (news_id, seq, text)"
                        " VALUES (%s, %s, %s)",
                        claims,
                    )
                if links:
                    await cur.executemany(
                        "INSERT INTO ai.duplicate_link (news_id, canonical_id,"
                        " dup_type, level, score, stale)"
                        " VALUES (%s, %s, %s, %s, %s, %s)",
                        links,
                    )
