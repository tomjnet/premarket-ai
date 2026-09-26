"""L3: paraphrases, by embedding similarity plus the fact guard.

::

    unique after L0-L2 -> embed -> KNN top 5 (earlier, within the window)
      cosine >= 0.90 and same tickers?
        same key numbers and >= 10 words differ -> PARAPHRASE (L3 link)
        < 10 words differ, other facts/details  -> CONFLICTING VERSION
      otherwise                                 -> unique: index it

A paraphrase is the same story in other words: the same companies and the
same numbers. A nearly identical text of the same feed date that changes a
number or a detail is not a copy: it stays in the feed and carries the
other version as evidence (``check: dedup``, no reason code), for the
increment 4 judge. It isn't a badge: on vendor-sim data the conflicting
versions were all real stories (a company's two dividend items of one day),
so as a flag it would only mislead.

The vectors live in Redis (RedisVL index ``idx:dedup:<dims>``, hashes
``dedup:vec:<dims>:<news id>`` that expire with the window); Postgres keeps
the embeddings (``ai.news_embedding``), so a lost index is rebuilt without
calling the embedding model again.
"""

from __future__ import annotations

from collections.abc import Sequence
import dataclasses
import datetime
import json
import re
from typing import Protocol
import unicodedata

import numpy as np
from redis import asyncio as aioredis
from redisvl.index import AsyncSearchIndex
from redisvl.query import VectorQuery

from ai_api.dedup import config
from ai_api.dedup import normalize
from ai_api.dedup import service

NEAREST = 5
_SPACES = re.compile(r"\s+")


def embed_text(headline: str, body: str) -> str:
    """The text L3 embeds: headline and story, without vendor boilerplate.

    Args:
        headline: The vendor headline.
        body: The vendor body.

    Returns:
        NFKC text with whitespace collapsed (casing kept: the embedding
        model reads it).
    """
    headline, body = normalize.strip_boilerplate(headline, body)
    text = unicodedata.normalize("NFKC", f"{headline}\n{body}")
    return _SPACES.sub(" ", text).strip()


@dataclasses.dataclass(frozen=True)
class VectorEntry:
    """An item in the L3 index.

    Attributes:
        news_id: The ``ai.news_item`` id.
        feed_date: Its feed date.
        vendor_item_id: The vendor's id (orders items within a day).
        tickers: Its tickers, upper case and sorted.
        facts: Its key numbers (``extract_key_numbers``).
        text: Its normalized story (``dedup_text``), to count word edits.
        vector: Its embedding.
    """

    news_id: int
    feed_date: datetime.date
    vendor_item_id: str
    tickers: tuple[str, ...]
    facts: tuple[str, ...]
    text: str
    vector: tuple[float, ...]

    @property
    def order(self) -> tuple[datetime.date, str]:
        """Earlier feed dates first, then the vendor's own sequence."""
        return (self.feed_date, self.vendor_item_id)

    @classmethod
    def of(
        cls, item: service.DedupItem, vector: Sequence[float]
    ) -> VectorEntry:
        """The entry of a vendor item and its embedding."""
        text = normalize.dedup_text(item.headline, item.body)
        return cls(
            news_id=item.news_id,
            feed_date=item.feed_date,
            vendor_item_id=item.vendor_item_id,
            tickers=tuple(sorted({t.upper() for t in item.tickers})),
            facts=tuple(normalize.extract_key_numbers(text)),
            text=text,
            vector=tuple(float(x) for x in vector),
        )


@dataclasses.dataclass(frozen=True)
class Conflict:
    """An earlier, very similar story with other facts.

    Attributes:
        canonical_id: The earlier item's news id.
        canonical_vendor_item_id: Its vendor id.
        canonical_feed_date: Its feed date.
        cosine: The embedding similarity.
        detail: What differs, in plain text.
    """

    canonical_id: int
    canonical_vendor_item_id: str
    canonical_feed_date: datetime.date
    cosine: float
    detail: str


class VectorIndex(Protocol):
    """Nearest-neighbor search over the indexed items."""

    async def nearest(
        self, vector: Sequence[float], k: int
    ) -> list[tuple[VectorEntry, float]]:
        """The ``k`` most similar entries and their cosine similarity."""
        ...

    async def add(self, entry: VectorEntry) -> None:
        """Indexes one entry."""
        ...


def _str(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return 0.0 if denominator == 0 else float(a @ b) / denominator


class MemoryVectorIndex:
    """An exact in-memory index (tests and the eval)."""

    def __init__(self) -> None:
        """Starts empty."""
        self._entries: dict[int, VectorEntry] = {}

    def __len__(self) -> int:
        """The number of entries."""
        return len(self._entries)

    async def nearest(
        self, vector: Sequence[float], k: int
    ) -> list[tuple[VectorEntry, float]]:
        """The ``k`` most similar entries (exact cosine)."""
        query = np.asarray(vector, dtype=np.float64)
        scored = [
            (entry, _cosine(query, np.asarray(entry.vector)))
            for entry in self._entries.values()
        ]
        scored.sort(key=lambda pair: -pair[1])
        return scored[:k]

    async def add(self, entry: VectorEntry) -> None:
        """Indexes (or replaces) one entry."""
        self._entries[entry.news_id] = entry


class RedisVectorIndex:
    """The L3 index in Redis 8 (query engine), through RedisVL."""

    def __init__(self, redis: aioredis.Redis, dims: int, ttl_s: int) -> None:
        """Uses ``redis``; vectors have ``dims`` floats and live ``ttl_s``.

        Args:
            redis: A client with ``decode_responses=False`` (vectors are
                binary).
            dims: The embedding size (the index name includes it, so a new
                embedding model gets a new index).
            ttl_s: Lifetime of each vector.
        """
        self._ttl_s = ttl_s
        self._dims = dims
        self._index = AsyncSearchIndex.from_dict(
            {
                "index": {
                    "name": f"idx:dedup:{dims}",
                    "prefix": f"dedup:vec:{dims}",
                    "storage_type": "hash",
                },
                "fields": [
                    {"name": "news_id", "type": "numeric"},
                    {"name": "feed_date", "type": "tag"},
                    {
                        "name": "embedding",
                        "type": "vector",
                        "attrs": {
                            "dims": dims,
                            "algorithm": "flat",
                            "distance_metric": "cosine",
                            "datatype": "float32",
                        },
                    },
                ],
            },
            redis_client=redis,
        )

    async def create(self) -> None:
        """Creates the index when it doesn't exist yet."""
        await self._index.create(overwrite=False)

    async def nearest(
        self, vector: Sequence[float], k: int
    ) -> list[tuple[VectorEntry, float]]:
        """The ``k`` most similar entries (Redis returns cosine distance)."""
        query = VectorQuery(
            vector=list(vector),
            vector_field_name="embedding",
            return_fields=[
                "news_id",
                "feed_date",
                "vendor_item_id",
                "tickers",
                "facts",
                "text",
            ],
            num_results=k,
            dtype="float32",
        )
        found = []
        for doc in await self._index.query(query):
            try:
                # The candidates' own vectors aren't needed: only the score.
                entry = VectorEntry(
                    news_id=int(_str(doc["news_id"])),
                    feed_date=datetime.date.fromisoformat(
                        _str(doc["feed_date"])
                    ),
                    vendor_item_id=_str(doc["vendor_item_id"]),
                    tickers=tuple(json.loads(_str(doc["tickers"]))),
                    facts=tuple(json.loads(_str(doc["facts"]))),
                    text=_str(doc["text"]),
                    vector=(),
                )
                distance = float(_str(doc["vector_distance"]))
            except (KeyError, ValueError):
                continue
            found.append((entry, 1.0 - distance))
        return found

    async def add(self, entry: VectorEntry) -> None:
        """Indexes one entry; it expires with the window."""
        record = {
            "news_id": entry.news_id,
            "feed_date": entry.feed_date.isoformat(),
            "vendor_item_id": entry.vendor_item_id,
            "tickers": json.dumps(list(entry.tickers)),
            "facts": json.dumps(list(entry.facts)),
            "text": entry.text,
            "embedding": np.asarray(entry.vector, dtype=np.float32).tobytes(),
        }
        await self._index.load([record], id_field="news_id", ttl=self._ttl_s)


def _difference(candidate: VectorEntry, item: VectorEntry, edits: int) -> str:
    if candidate.facts != item.facts:
        before = ", ".join(sorted(set(candidate.facts) - set(item.facts)))
        after = ", ".join(sorted(set(item.facts) - set(candidate.facts)))
        return f"key facts differ ({before or 'none'} vs {after or 'none'})"
    return f"only {edits} words differ, with other details"


class ParaphraseCheck:
    """Runs L3 on items that L0-L2 found unique, in feed order."""

    def __init__(
        self,
        index: VectorIndex,
        cfg: config.DedupConfig,
        nearest: int = NEAREST,
    ) -> None:
        """Uses ``index`` with the thresholds in ``cfg``."""
        self._index = index
        self._cfg = cfg
        self._nearest = nearest

    def _usable(self, candidate: VectorEntry, item: VectorEntry) -> bool:
        oldest = item.feed_date - datetime.timedelta(days=self._cfg.window_days)
        return candidate.order < item.order and candidate.feed_date >= oldest

    async def check(
        self, item: VectorEntry
    ) -> tuple[service.DedupMatch | None, Conflict | None]:
        """Checks one item; indexes it unless it's a paraphrase.

        Args:
            item: The item and its embedding.

        Returns:
            ``(match, None)`` for a paraphrase of an earlier item, else
            ``(None, conflict)`` where ``conflict`` is the closest earlier
            story with other facts, or None.
        """
        best: tuple[float, VectorEntry, int] | None = None
        conflict: tuple[float, VectorEntry, int] | None = None
        for candidate, cosine in await self._index.nearest(
            item.vector, self._nearest
        ):
            if candidate.news_id == item.news_id:
                continue
            if not self._usable(candidate, item):
                continue
            if cosine < self._cfg.cosine_min:
                continue
            if candidate.tickers != item.tickers:
                continue
            edits = service.word_edits(candidate.text, item.text)
            same_facts = candidate.facts == item.facts
            # A close text with the same facts is a copy L2 missed.
            if same_facts and (
                edits >= self._cfg.paraphrase_min_word_edits
                or edits <= self._cfg.near_max_word_edits
            ):
                if best is None or cosine > best[0]:
                    best = (cosine, candidate, edits)
            # A conflicting version is nearly the same text with other
            # facts or details. Stories that share only a template (two
            # earnings items of one company, reworded) are not: measured on
            # vendor-sim, that rule flagged 52 of 88 items of a day.
            elif (
                edits < self._cfg.paraphrase_min_word_edits
                and candidate.feed_date == item.feed_date
                and (conflict is None or cosine > conflict[0])
            ):
                conflict = (cosine, candidate, edits)
        if best is not None:
            cosine, original, edits = best
            return (
                service.DedupMatch(
                    canonical_id=original.news_id,
                    canonical_vendor_item_id=original.vendor_item_id,
                    canonical_feed_date=original.feed_date,
                    dup_type="paraphrase",
                    level="L3",
                    score=round(cosine, 4),
                    word_edits=edits,
                    stale=original.feed_date < item.feed_date,
                ),
                None,
            )
        await self._index.add(item)
        if conflict is None:
            return None, None
        cosine, original, edits = conflict
        return None, Conflict(
            canonical_id=original.news_id,
            canonical_vendor_item_id=original.vendor_item_id,
            canonical_feed_date=original.feed_date,
            cosine=round(cosine, 4),
            detail=_difference(original, item, edits),
        )

    async def index_unique(self, entries: Sequence[VectorEntry]) -> None:
        """Re-indexes items already known to be unique (warm-up)."""
        for entry in entries:
            await self._index.add(entry)
