"""``search_news``: the trusted corpus in the active vector store.

The corpus (EDGAR 8-Ks and their press releases, XBRL fact sheets, Fed and
SEC releases) is indexed by ``ai-api corpus`` into the store VECTOR_STORE
names. The query is embedded through the LLM gateway with the same model,
then searched, optionally for one ticker and a window of days before a
date:

- ``pgvector`` (increment 6): ``ai.chunk.embedding``, read with the MCP
  server's read-only role. Hybrid like the chat: the vector neighbours and
  the Postgres full-text matches fused by reciprocal rank, with the ticker
  and the date window applied in SQL.
- ``chroma`` (increments 3 to 5): Chroma filters dates only as numbers, so
  the window is applied to the ``published_at`` text after a wider search.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

import chromadb
import httpx
from psycopg import rows
from psycopg_pool import AsyncConnectionPool

from mcp_server import config

_OVERFETCH = 4
_MAX_TEXT_CHARS = 1500
_MAX_K = 20
# Reciprocal rank fusion constant (the same as ai-api's chat).
_RRF_K = 60

# ``%(filters)s`` is filled in from fixed strings only (never user text).
_HYBRID_SQL = """
WITH q AS (
  SELECT replace(plainto_tsquery('english', %(text)s)::text, '&', '|')
         ::tsquery AS query
),
vec AS (
  SELECT id, row_number() OVER (ORDER BY distance) AS rank
  FROM (
    SELECT id, embedding <=> %(vector)s::vector AS distance
    FROM ai.chunk
    WHERE embedding IS NOT NULL {filters}
    ORDER BY embedding <=> %(vector)s::vector
    LIMIT %(candidates)s
  ) nearest
),
fts AS (
  SELECT id, row_number() OVER (ORDER BY score DESC, id) AS rank
  FROM (
    SELECT c.id, ts_rank_cd(c.tsv, q.query) AS score
    FROM ai.chunk c, q
    WHERE c.embedding IS NOT NULL AND c.tsv @@ q.query {filters}
    ORDER BY score DESC, c.id
    LIMIT %(candidates)s
  ) matched
),
fused AS (
  SELECT id,
         coalesce(1.0 / (%(rrf_k)s + vec.rank), 0)
         + coalesce(1.0 / (%(rrf_k)s + fts.rank), 0) AS score
  FROM vec FULL JOIN fts USING (id)
)
SELECT c.text, c.metadata, c.embedding <=> %(vector)s::vector AS distance
FROM fused f JOIN ai.chunk c ON c.id = f.id
ORDER BY f.score DESC, distance
LIMIT %(k)s
"""


class CorpusError(RuntimeError):
    """The embedding model or the vector store failed."""


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class Corpus:
    """Search over the trusted corpus."""

    def __init__(
        self,
        settings: config.Settings,
        http: httpx.AsyncClient,
        client: Any = None,
        pool: AsyncConnectionPool | None = None,
    ) -> None:
        """Connects lazily to the store.

        Args:
            settings: The settings (VECTOR_STORE, the gateway).
            http: The HTTP client (embeddings).
            client: A Chroma client (tests); None connects over HTTP.
            pool: The read-only database pool (pgvector).
        """
        self._settings = settings
        self._http = http
        self._client = client
        self._pool = pool

    async def _embed(self, query: str) -> list[float]:
        settings = self._settings
        try:
            response = await self._http.post(
                f"{settings.gateway_url}/embeddings",
                headers={"Authorization": f"Bearer {settings.gateway_key}"},
                json={
                    "model": settings.embed_model,
                    "input": [settings.query_prefix + query],
                },
                timeout=60,
            )
            response.raise_for_status()
            return list(response.json()["data"][0]["embedding"])
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise CorpusError(f"embedding failed: {e!r}") from e

    def _chroma_query(
        self, vector: list[float], ticker: str | None, n: int
    ) -> dict[str, Any]:
        if self._client is None:
            self._client = chromadb.HttpClient(
                host=self._settings.chroma_host,
                port=self._settings.chroma_port,
            )
        collection = self._client.get_collection(self._settings.collection)
        built_with = (collection.metadata or {}).get("embed_model")
        if built_with != self._settings.embed_model:
            raise CorpusError(
                f"the corpus was indexed with {built_with}, not "
                f"{self._settings.embed_model}"
            )
        return collection.query(
            query_embeddings=[vector],
            n_results=n,
            where={"ticker": ticker} if ticker else None,
            include=["documents", "metadatas", "distances"],
        )

    async def _chroma(
        self,
        vector: list[float],
        ticker: str | None,
        first: datetime.date | None,
        last: datetime.date | None,
        k: int,
    ) -> list[tuple[str, dict[str, Any], float]]:
        wanted = k * _OVERFETCH if last is not None else k
        found = await asyncio.to_thread(
            self._chroma_query, vector, ticker, wanted
        )
        kept = []
        for text, meta, distance in zip(
            found["documents"][0],
            found["metadatas"][0],
            found["distances"][0],
            strict=True,
        ):
            published = str(meta.get("published_at") or "")[:10]
            if last is not None:
                if not published:
                    continue
                day = datetime.date.fromisoformat(published)
                if not first <= day <= last:
                    continue
            kept.append((text or "", meta, float(distance)))
            if len(kept) == k:
                break
        return kept

    async def _pgvector(
        self,
        query: str,
        vector: list[float],
        ticker: str | None,
        first: datetime.date | None,
        last: datetime.date | None,
        k: int,
    ) -> list[tuple[str, dict[str, Any], float]]:
        if self._pool is None:
            raise CorpusError("no database pool for the pgvector store")
        filters = ""
        if ticker:
            filters += " AND metadata->>'ticker' = %(ticker)s"
        if last is not None:
            # ISO dates compare as text.
            filters += (
                " AND metadata->>'published_at' BETWEEN %(first)s AND %(last)s"
            )
        candidates = k * _OVERFETCH
        params = {
            "text": query,
            "vector": _vector_literal(vector),
            "ticker": ticker,
            "first": None if first is None else first.isoformat(),
            "last": None if last is None else last.isoformat(),
            "candidates": candidates,
            "rrf_k": _RRF_K,
            "k": k,
        }
        async with self._pool.connection() as conn, conn.transaction():
            # Filtered HNSW scans keep going until enough rows match.
            await conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
            await conn.execute(
                f"SET LOCAL hnsw.ef_search = {max(40, candidates)}"
            )
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(_HYBRID_SQL.format(filters=filters), params)
            found = await cur.fetchall()
        return [
            (row["text"], dict(row["metadata"] or {}), float(row["distance"]))
            for row in found
        ]

    async def search(
        self,
        query: str,
        date: datetime.date | None = None,
        ticker: str | None = None,
        days: int = 7,
        k: int = 8,
    ) -> dict[str, Any]:
        """The best chunks.

        Args:
            query: What to look for.
            date: Only chunks published in the ``days`` up to this date.
            ticker: Only this company's documents.
            days: The window before ``date``.
            k: How many results (at most 20).

        Returns:
            ``results``: ``title``, ``url``, ``source``, ``ticker``,
            ``published_at``, ``text`` and ``distance``, best first.

        Raises:
            CorpusError: The embedding model or the store failed.
        """
        k = max(1, min(k, _MAX_K))
        vector = await self._embed(query)
        first = None if date is None else date - datetime.timedelta(days=days)
        try:
            if self._settings.vector_store == "pgvector":
                found = await self._pgvector(
                    query, vector, ticker, first, date, k
                )
            else:
                found = await self._chroma(vector, ticker, first, date, k)
        except CorpusError:
            raise
        except Exception as e:  # noqa: BLE001 - the store's errors vary.
            raise CorpusError(f"vector search failed: {e!r}") from e
        results = []
        for text, meta, distance in found:
            published = str(meta.get("published_at") or "")[:10]
            results.append(
                {
                    "title": meta.get("title", ""),
                    "url": meta.get("url", ""),
                    "source": meta.get("source", ""),
                    "ticker": meta.get("ticker"),
                    "published_at": published or None,
                    "text": text[:_MAX_TEXT_CHARS],
                    "distance": round(distance, 4),
                }
            )
        return {"results": results}
