"""The cross-encoder reranker (``bge-reranker-base`` on CPU).

It runs in its own container (Hugging Face text-embeddings-inference, the
``reranker`` service), so the API image stays small. Vector search finds
20 candidates; the reranker reads each one next to the question and keeps
the best 5. If it's down, the vector order is used and the answer says so
in its metadata.
"""

from __future__ import annotations

from collections.abc import Sequence
import logging

import httpx

_log = logging.getLogger(__name__)
_MAX_TEXT_CHARS = 2000


class Reranker:
    """Client of the TEI ``/rerank`` endpoint."""

    def __init__(
        self,
        url: str,
        timeout_s: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Talks to ``url`` (empty: reranking off)."""
        self._url = url
        self._client = client
        if self._client is None and url:
            self._client = httpx.AsyncClient(timeout=timeout_s)

    @property
    def enabled(self) -> bool:
        """True when a reranker is configured."""
        return bool(self._url)

    async def aclose(self) -> None:
        """Closes the HTTP client."""
        if self._client is not None:
            await self._client.aclose()

    async def rank(
        self, query: str, texts: Sequence[str]
    ) -> list[tuple[int, float]] | None:
        """Indexes of ``texts``, best first, with their scores.

        Args:
            query: The question.
            texts: The candidates.

        Returns:
            (index, score) pairs, best first; None when the reranker is off
            or failed (callers keep the vector order).
        """
        if not self._url or not texts:
            return None
        try:
            response = await self._client.post(
                f"{self._url}/rerank",
                json={
                    "query": query,
                    "texts": [t[:_MAX_TEXT_CHARS] for t in texts],
                    "truncate": True,
                },
            )
            response.raise_for_status()
            ranked = [
                (int(entry["index"]), float(entry["score"]))
                for entry in response.json()
            ]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
            _log.warning("reranker unavailable, using vector order: %r", e)
            return None
        ranked.sort(key=lambda pair: -pair[1])
        return ranked
