"""``ai-api corpus`` and ``ai-api reindex``: the trusted corpus.

``corpus`` downloads what's new (see ``sources``), stores each document in
``ai.document``, splits it into ``ai.chunk`` rows and indexes the chunks
that aren't in the vector store yet. Documents already stored are not
fetched again, except the company fact sheets, which are refreshed (a
changed sheet replaces its chunks). ``reindex`` rebuilds the vector store
from ``ai.chunk`` (after a model change or a lost volume).
"""

from __future__ import annotations

from collections.abc import Sequence
import dataclasses
import datetime
import hashlib
import logging
from typing import Any

import psycopg
from psycopg import rows
from psycopg.types import json as pg_json
from redis import asyncio as aioredis

from ai_api import config
from ai_api.llm import factory
from ai_api.rag import chunking
from ai_api.rag import sources
from ai_api.rag import store as store_lib
from ai_api.rag import universe
from ai_api.rules import ratelimit
from ai_api.rules import repository as rules_repository
from ai_api.rules import runner as rules_runner

_log = logging.getLogger(__name__)
_EDGAR_RATE_PER_S = 10
_OTHER_RATE_PER_S = 2
_INDEX_BATCH = 32


class CorpusError(RuntimeError):
    """The corpus can't be built (missing settings or registry)."""


@dataclasses.dataclass(frozen=True)
class CorpusCounts:
    """What a corpus run did."""

    fetched: int
    changed: int
    chunks_indexed: int
    documents: int
    chunks: int
    failures: int


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class CorpusRepository:
    """``ai.document`` and ``ai.chunk`` (owner connection, autocommit)."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        """Uses ``conn``."""
        self._conn = conn

    async def _all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor(row_factory=rows.dict_row)
        await cur.execute(sql, params)
        return await cur.fetchall()

    async def known_urls(self) -> set[str]:
        """URLs of the stored documents."""
        return {
            r["url"] for r in await self._all("SELECT url FROM ai.document")
        }

    async def upsert(
        self, document: sources.Document, chunk_chars: int, overlap: int
    ) -> tuple[bool, list[int]]:
        """Stores a document and its chunks when it's new or changed.

        Returns:
            (changed, ids of the chunks it replaced).
        """
        digest = _sha256(document.text)
        found = await self._all(
            "SELECT id, content_sha256 FROM ai.document WHERE url = %s",
            (document.url,),
        )
        if found and found[0]["content_sha256"] == digest:
            return False, []
        chunks = chunking.split(document.text, chunk_chars, overlap)
        async with self._conn.transaction():
            old = []
            if found:
                doc_id = found[0]["id"]
                old = [
                    r["id"]
                    for r in await self._all(
                        "SELECT id FROM ai.chunk WHERE document_id = %s",
                        (doc_id,),
                    )
                ]
                await self._conn.execute(
                    "DELETE FROM ai.chunk WHERE document_id = %s", (doc_id,)
                )
                await self._conn.execute(
                    "UPDATE ai.document SET title = %s, text = %s,"
                    " content_sha256 = %s, published_at = %s,"
                    " fetched_at = now() WHERE id = %s",
                    (
                        document.title,
                        document.text,
                        digest,
                        document.published_at,
                        doc_id,
                    ),
                )
            else:
                inserted = await self._all(
                    "INSERT INTO ai.document (source, url, title, ticker, cik,"
                    " published_at, content_sha256, text)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        document.source,
                        document.url,
                        document.title,
                        document.ticker,
                        document.cik,
                        document.published_at,
                        digest,
                        document.text,
                    ),
                )
                doc_id = inserted[0]["id"]
            metadata = {
                "source": document.source,
                "title": document.title,
                "url": document.url,
                "ticker": document.ticker,
                "published_at": None
                if document.published_at is None
                else document.published_at.date().isoformat(),
            }
            async with self._conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO ai.chunk (document_id, seq, text, metadata)"
                    " VALUES (%s, %s, %s, %s)",
                    [
                        (doc_id, i, text, pg_json.Jsonb(metadata))
                        for i, text in enumerate(chunks)
                    ],
                )
        return True, old

    async def unindexed(self, embed_model: str) -> list[dict[str, Any]]:
        """Chunks not in the vector store with ``embed_model``."""
        return await self._all(
            "SELECT id, text, metadata FROM ai.chunk"
            " WHERE indexed_at IS NULL OR embed_model IS DISTINCT FROM %s"
            " ORDER BY id",
            (embed_model,),
        )

    async def mark_indexed(self, ids: Sequence[int], embed_model: str) -> None:
        """Records that these chunks are in the vector store."""
        await self._conn.execute(
            "UPDATE ai.chunk SET indexed_at = now(), embed_model = %s"
            " WHERE id = ANY (%s)",
            (embed_model, list(ids)),
        )

    async def unmark_all(self) -> None:
        """Marks every chunk as not indexed (reindex)."""
        await self._conn.execute(
            "UPDATE ai.chunk SET indexed_at = NULL, embed_model = NULL"
        )

    async def totals(self) -> tuple[int, int]:
        """(documents, chunks)."""
        found = await self._all(
            "SELECT (SELECT count(*) FROM ai.document) AS documents,"
            " (SELECT count(*) FROM ai.chunk) AS chunks"
        )
        return found[0]["documents"], found[0]["chunks"]


def _store(settings: config.AiSettings) -> store_lib.CorpusStore:
    llm = settings.llm
    embeddings = store_lib.PrefixedEmbeddings(
        factory.embeddings(llm), llm.query_prefix, llm.document_prefix
    )
    return store_lib.CorpusStore(settings.rag, embeddings, llm.embed_model)


async def _index(
    repo: CorpusRepository, store: store_lib.CorpusStore, embed_model: str
) -> int:
    pending = await repo.unindexed(embed_model)
    for start in range(0, len(pending), _INDEX_BATCH):
        batch = pending[start : start + _INDEX_BATCH]
        ids = [row["id"] for row in batch]
        await store.add(
            ids,
            [row["text"] for row in batch],
            [dict(row["metadata"], chunk_id=row["id"]) for row in batch],
        )
        await repo.mark_indexed(ids, embed_model)
        _log.info("indexed %d/%d chunks", start + len(batch), len(pending))
    return len(pending)


async def _companies(
    conn: psycopg.AsyncConnection,
    redis: aioredis.Redis,
    settings: config.AiSettings,
) -> list[sources.Company]:
    rules_settings = config.RulesSettings(
        owner=settings.owner,
        redis_host=settings.redis_host,
        redis_password=settings.redis_password,
        sec_user_agent=settings.sec_user_agent,
    )
    registry = await rules_runner.ensure_registry(
        rules_repository.RulesRepository(conn), redis, rules_settings
    )
    if registry is None:
        raise CorpusError(
            "no SEC ticker registry: set SEC_USER_AGENT and run "
            "`make -C python registry`"
        )
    found = []
    for member in universe.load(settings.config_dir):
        company = registry.company(member.ticker)
        if company is None:
            _log.warning("%s isn't in the SEC registry", member.ticker)
            continue
        found.append(sources.Company(member.ticker, member.name, company.cik))
    return found


async def build(settings: config.AiSettings) -> CorpusCounts:
    """Downloads what's new, stores it and indexes new chunks.

    Raises:
        CorpusError: SEC_USER_AGENT or the registry is missing.
    """
    if not settings.sec_user_agent:
        raise CorpusError(
            "SEC_USER_AGENT is empty: SEC requires a name and contact email"
        )
    rag = settings.rag
    since = datetime.date.today() - datetime.timedelta(
        days=31 * rag.corpus_months
    )
    redis = aioredis.Redis(
        host=settings.redis_host,
        password=settings.redis_password,
        decode_responses=True,
    )
    fetcher = sources.Fetcher(
        settings.sec_user_agent,
        ratelimit.TokenBucket(redis, "edgar", _EDGAR_RATE_PER_S),
        ratelimit.TokenBucket(redis, "corpus-other", _OTHER_RATE_PER_S),
    )
    fetched = changed = failures = 0
    replaced: list[int] = []
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.owner.dsn(), autocommit=True
        ) as conn:
            repo = CorpusRepository(conn)
            companies = await _companies(conn, redis, settings)
            known = await repo.known_urls()

            async def keep(documents: Sequence[sources.Document]) -> None:
                nonlocal fetched, changed
                for document in documents:
                    fetched += 1
                    was_changed, old = await repo.upsert(
                        document, rag.chunk_chars, rag.chunk_overlap
                    )
                    changed += was_changed
                    replaced.extend(old)

            for company in companies:
                try:
                    await keep(
                        await sources.company_filings(
                            fetcher, company, since, rag.max_filings, known
                        )
                    )
                    facts = await sources.company_facts(fetcher, company)
                    await keep([] if facts is None else [facts])
                except sources.SourceError as e:
                    failures += 1
                    _log.warning("%s: %s", company.ticker, e)
                _log.info("corpus: %s done", company.ticker)
            for feed, source in (
                (sources.FED_RSS, "fed_press"),
                (sources.SEC_RSS, "sec_press"),
            ):
                try:
                    await keep(
                        await sources.press_releases(
                            fetcher,
                            feed,
                            source,
                            since,
                            rag.max_releases,
                            known,
                        )
                    )
                except sources.SourceError as e:
                    failures += 1
                    _log.warning("%s: %s", source, e)
            store = _store(settings)
            await store.delete(replaced)
            indexed = await _index(repo, store, settings.llm.embed_model)
            documents, chunks = await repo.totals()
    finally:
        await fetcher.aclose()
        await redis.aclose()
    return CorpusCounts(fetched, changed, indexed, documents, chunks, failures)


async def reindex(settings: config.AiSettings) -> int:
    """Rebuilds the vector store from ``ai.chunk``; returns the chunks."""
    async with await psycopg.AsyncConnection.connect(
        settings.owner.dsn(), autocommit=True
    ) as conn:
        repo = CorpusRepository(conn)
        store = _store(settings)
        store.reset()
        await repo.unmark_all()
        return await _index(repo, store, settings.llm.embed_model)
