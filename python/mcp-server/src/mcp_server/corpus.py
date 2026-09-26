"""``search_news``: the trusted corpus in the active vector store.

The corpus (EDGAR 8-Ks and their press releases, XBRL fact sheets, Fed and
SEC releases) is indexed by ``ai-api corpus`` into ChromaDB (increments 3
to 5). The query is embedded through the LLM gateway with the same model,
then searched, optionally for one ticker and a window of days before a
date. Chroma filters dates only as numbers, so the window is applied to
the ``published_at`` text after a wider search.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

import chromadb
import httpx

from mcp_server import config

_OVERFETCH = 4
_MAX_TEXT_CHARS = 1500
_MAX_K = 20


class CorpusError(RuntimeError):
    """The embedding model or the vector store failed."""


class Corpus:
    """Vector search over the trusted corpus."""

    def __init__(
        self,
        settings: config.Settings,
        http: httpx.AsyncClient,
        client: Any = None,
    ) -> None:
        """Connects lazily to Chroma (or uses ``client`` in tests)."""
        self._settings = settings
        self._http = http
        self._client = client

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

    def _query(
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

    async def search(
        self,
        query: str,
        date: datetime.date | None = None,
        ticker: str | None = None,
        days: int = 7,
        k: int = 8,
    ) -> dict[str, Any]:
        """The closest chunks.

        Args:
            query: What to look for.
            date: Only chunks published in the ``days`` up to this date.
            ticker: Only this company's documents.
            days: The window before ``date``.
            k: How many results (at most 20).

        Returns:
            ``results``: ``title``, ``url``, ``source``, ``ticker``,
            ``published_at``, ``text`` and ``distance``, closest first.

        Raises:
            CorpusError: The embedding model or the store failed.
        """
        k = max(1, min(k, _MAX_K))
        vector = await self._embed(query)
        wanted = k * _OVERFETCH if date is not None else k
        try:
            found = await asyncio.to_thread(self._query, vector, ticker, wanted)
        except CorpusError:
            raise
        except Exception as e:  # noqa: BLE001 - the store's errors vary.
            raise CorpusError(f"vector search failed: {e!r}") from e
        first = None if date is None else date - datetime.timedelta(days=days)
        results = []
        for text, meta, distance in zip(
            found["documents"][0],
            found["metadatas"][0],
            found["distances"][0],
            strict=True,
        ):
            published = str(meta.get("published_at") or "")[:10]
            if date is not None:
                if not published:
                    continue
                day = datetime.date.fromisoformat(published)
                if not first <= day <= date:
                    continue
            results.append(
                {
                    "title": meta.get("title", ""),
                    "url": meta.get("url", ""),
                    "source": meta.get("source", ""),
                    "ticker": meta.get("ticker"),
                    "published_at": published or None,
                    "text": (text or "")[:_MAX_TEXT_CHARS],
                    "distance": round(float(distance), 4),
                }
            )
            if len(results) == k:
                break
        return {"results": results}
