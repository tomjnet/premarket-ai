"""The semantic answer cache of "Ask the News" (RedisVL ``SemanticCache``).

When a question close enough to one already answered for the same feed
date comes again, the stored answer (its text, citations and sources) is
sent without retrieval, agents or a model call. Several traders asking
about the same headline in the pre-market rush then cost one answer.

- The key is the question's embedding (the RAG embedding model with its
  query prefix), searched within ``CHAT_CACHE_DISTANCE`` of cosine
  distance, and only among answers for the same feed date.
- Guard, as in dedup L3: the cached question must name the same companies.
  "What did Apple announce?" and "What did Microsoft announce?" embed
  close together but are different questions.
- Never cached: refusals, answers without sources, and questions about the
  user's own watchlist (the answer is personal).
- An entry is used for ``CHAT_CACHE_TTL_S`` after it was written (15
  minutes): verdicts change while analysts review, so a cached answer never
  gets older than that. RedisVL refreshes an entry's expiry on every hit,
  so the age is checked against the time it was written, not the expiry.

Redis is only a cache here: losing it loses nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
import datetime
import json
import logging
import re
import time
from typing import Any, Protocol

from langchain_core import embeddings as lc_embeddings

_log = logging.getLogger(__name__)
_FEED_DATE = "feed_date"
_CANDIDATES = 3
# "my watchlist", "our positions", "should I…": the answer depends on who
# asks ("tell me about Apple" doesn't).
_PERSONAL = re.compile(
    r"\b(my|mine|our|ours|watchlist|portfolio|should\s+i|do\s+i|can\s+i)\b",
    re.IGNORECASE,
)


class Backend(Protocol):
    """The two calls of RedisVL's ``SemanticCache`` the cache makes."""

    async def acheck(
        self,
        vector: list[float] | None = None,
        num_results: int = 1,
        filter_expression: Any = None,
    ) -> list[dict[str, Any]]:
        """Entries within the distance threshold, nearest first."""
        ...

    async def astore(
        self,
        prompt: str,
        response: str,
        vector: list[float] | None = None,
        metadata: dict[str, Any] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> str:
        """Stores one entry; returns its key."""
        ...


def personal(question: str) -> bool:
    """True for a question whose answer depends on who asks."""
    return bool(_PERSONAL.search(question))


def build_backend(
    redis_url: str, dims: int, ttl_s: int, distance: float
) -> Any:
    """RedisVL's ``SemanticCache`` for vectors computed by the caller.

    Blocking (it creates the index): call it in a thread.

    Args:
        redis_url: ``redis://:password@host:port/0``.
        dims: The embedding size; it names the index, like dedup L3's.
        ttl_s: Expiry of an entry.
        distance: Largest cosine distance of a hit (0 to 2).

    Returns:
        The cache.
    """
    from redisvl.extensions.cache.llm import SemanticCache  # noqa: PLC0415
    from redisvl.utils.vectorize import custom  # noqa: PLC0415

    # The cache is always given vectors: this function only tells RedisVL
    # the vector size (it embeds one test string when it starts).
    vectorizer = custom.CustomVectorizer(embed=lambda _text: [0.0] * dims)
    return SemanticCache(
        name=f"semcache:chat:{dims}",
        distance_threshold=distance,
        ttl=ttl_s,
        vectorizer=vectorizer,
        filterable_fields=[{"name": _FEED_DATE, "type": "tag"}],
        redis_url=redis_url,
    )


class AnswerCache:
    """Finds and stores answers (see the module docstring)."""

    def __init__(
        self,
        backend: Backend,
        embeddings: lc_embeddings.Embeddings,
        ttl_s: int,
    ) -> None:
        """Wires the cache.

        Args:
            backend: The RedisVL cache (or a test double).
            embeddings: Query embeddings (with the query prefix).
            ttl_s: How long after it was written an answer may be used.
        """
        self._backend = backend
        self._embeddings = embeddings
        self._ttl_s = ttl_s

    def _filter(self, day: datetime.date) -> Any:
        from redisvl.query import filter as rv_filter  # noqa: PLC0415

        return rv_filter.Tag(_FEED_DATE) == day.isoformat()

    async def lookup(
        self, question: str, day: datetime.date, tickers: Sequence[str]
    ) -> dict[str, Any] | None:
        """A cached answer to ``question``, or None.

        Args:
            question: The sanitized question.
            day: The feed date.
            tickers: The universe tickers it names (the guard).

        Returns:
            ``{"vector", "hit"}``: always the question's vector (so a miss
            can be stored without embedding again), and the cached
            ``sources`` / ``reranked`` / ``done`` payload or None.
        """
        vector = await self._embeddings.aembed_query(question)
        try:
            found = await self._backend.acheck(
                vector=vector,
                num_results=_CANDIDATES,
                filter_expression=self._filter(day),
            )
        except Exception as e:  # noqa: BLE001 - a cache never fails a chat.
            _log.warning("semantic cache unavailable: %r", e)
            return {"vector": vector, "hit": None}
        wanted = sorted(tickers)
        now = time.time()
        for entry in found:
            meta = entry.get("metadata") or {}
            if isinstance(meta, str):
                meta = json.loads(meta)
            written = float(entry.get("inserted_at") or 0)
            if sorted(meta.get("tickers", [])) != wanted:
                continue
            if now - written > self._ttl_s:
                continue
            payload = json.loads(entry["response"])
            payload["distance"] = float(entry.get("vector_distance", 0))
            return {"vector": vector, "hit": payload}
        return {"vector": vector, "hit": None}

    async def store(
        self,
        question: str,
        day: datetime.date,
        tickers: Sequence[str],
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        """Stores an answer (never raises).

        Args:
            question: The sanitized question.
            day: The feed date.
            tickers: The universe tickers it names.
            vector: Its embedding (from ``lookup``).
            payload: ``sources``, ``reranked`` and the ``done`` data.
        """
        try:
            await self._backend.astore(
                prompt=question,
                response=json.dumps(payload),
                vector=vector,
                metadata={"tickers": sorted(tickers)},
                filters={_FEED_DATE: day.isoformat()},
            )
        except Exception as e:  # noqa: BLE001 - a cache never fails a chat.
            _log.warning("semantic cache store failed: %r", e)
