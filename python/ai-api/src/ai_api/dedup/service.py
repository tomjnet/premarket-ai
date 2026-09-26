"""``DedupService``: cheap checks first, stop at the first match.

::

    item -> L0 canonical URL -> L1 exact hash -> L2 SimHash + guard -> UNIQUE
              | hit              | hit            | hit
              +------------------+----------------+--> DUPLICATE of an
                                                       earlier item

Items are checked one at a time, in order: earlier feed dates first, then
the vendor's own item sequence, so the first copy the vendor wrote is the
original. A match must be earlier than the item and within the window. A
match from an earlier feed date is *stale*: old news re-served as today's.
Level L3 (embeddings, paraphrases) arrives with the embedding model in
increment 3.
"""

from __future__ import annotations

import collections
from collections.abc import Sequence
import dataclasses
import datetime
import hashlib

from ai_api.dedup import config
from ai_api.dedup import normalize
from ai_api.dedup import simhash
from ai_api.dedup import store


@dataclasses.dataclass(frozen=True)
class DedupItem:
    """One vendor item as the duplicate check sees it.

    Attributes:
        news_id: The ``ai.news_item`` id.
        feed_date: The feed date.
        vendor_item_id: The vendor's id.
        headline: The vendor headline.
        body: The vendor body.
        source_url: The source link.
        tickers: The vendor's tickers.
    """

    news_id: int
    feed_date: datetime.date
    vendor_item_id: str
    headline: str
    body: str
    source_url: str
    tickers: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class DedupMatch:
    """The earlier item a duplicate copies.

    Attributes:
        canonical_id: The original's news id.
        canonical_vendor_item_id: The original's vendor id.
        canonical_feed_date: The original's feed date.
        dup_type: ``url``, ``exact`` or ``near``.
        level: ``L0``, ``L1`` or ``L2``.
        score: For L2, the SimHash Hamming distance; else None.
        word_edits: For L2, how many words differ; else None.
        stale: The original is from an earlier feed date.
    """

    canonical_id: int
    canonical_vendor_item_id: str
    canonical_feed_date: datetime.date
    dup_type: str
    level: str
    score: float | None = None
    word_edits: int | None = None
    stale: bool = False


@dataclasses.dataclass(frozen=True)
class _Features:
    url_key: str | None
    exact_key: str
    indexed: store.IndexedItem
    band_keys: tuple[str, ...]


def word_edits(a: str, b: str) -> int:
    """Words in one text but not the other, counted with multiplicity.

    Args:
        a: A normalized text.
        b: Another normalized text.

    Returns:
        The size of the multiset symmetric difference of their words.
    """
    words_a = collections.Counter(a.split())
    words_b = collections.Counter(b.split())
    return sum((words_a - words_b).values()) + sum((words_b - words_a).values())


class DedupService:
    """Runs L0 to L2 against the Redis index and indexes unique items."""

    def __init__(self, index: store.DedupStore, cfg: config.DedupConfig):
        """Uses ``index`` with the thresholds in ``cfg``."""
        self._index = index
        self._cfg = cfg

    def _features(self, item: DedupItem) -> _Features:
        text = normalize.dedup_text(item.headline, item.body)
        try:
            url = normalize.canonical_url(item.source_url)
        except ValueError:
            url_key = None
        else:
            digest = hashlib.sha1(url.encode(), usedforsecurity=False)
            url_key = store.url_key(digest.hexdigest())
        value = simhash.simhash64(text, self._cfg.simhash_ngram)
        bands = self._cfg.bands
        band_keys = tuple(
            store.band_key(bands, i, band)
            for i, band in enumerate(simhash.band_keys(value, bands))
        )
        indexed = store.IndexedItem(
            news_id=item.news_id,
            feed_date=item.feed_date,
            vendor_item_id=item.vendor_item_id,
            simhash=value,
            tickers=tuple(sorted({t.upper() for t in item.tickers})),
            facts=tuple(normalize.extract_key_numbers(text)),
            text=text,
        )
        return _Features(
            url_key=url_key,
            exact_key=store.exact_key(normalize.sha256(text)),
            indexed=indexed,
            band_keys=band_keys,
        )

    def _usable(
        self, candidate: store.IndexedItem, item: store.IndexedItem
    ) -> bool:
        """An earlier item within the window (never the item itself)."""
        oldest = item.feed_date - datetime.timedelta(days=self._cfg.window_days)
        return candidate.order < item.order and candidate.feed_date >= oldest

    def _match(
        self,
        original: store.IndexedItem,
        item: store.IndexedItem,
        dup_type: str,
        level: str,
    ) -> DedupMatch:
        return DedupMatch(
            canonical_id=original.news_id,
            canonical_vendor_item_id=original.vendor_item_id,
            canonical_feed_date=original.feed_date,
            dup_type=dup_type,
            level=level,
            stale=original.feed_date < item.feed_date,
        )

    async def _level_hit(
        self, key: str | None, item: store.IndexedItem
    ) -> store.IndexedItem | None:
        if key is None:
            return None
        holder = await self._index.holder(key)
        if holder is None or holder == item.news_id:
            return None
        found = await self._index.items([holder])
        original = found.get(holder)
        if original is None or not self._usable(original, item):
            return None
        return original

    async def _near_hit(
        self, features: _Features
    ) -> tuple[store.IndexedItem, int, int] | None:
        item = features.indexed
        ids = await self._index.band_members(features.band_keys)
        ids.discard(item.news_id)
        best = None
        for candidate in (await self._index.items(ids)).values():
            if not self._usable(candidate, item):
                continue
            distance = simhash.hamming(candidate.simhash, item.simhash)
            if distance > self._cfg.simhash_max_hamming:
                continue
            # The guard: a different ticker or number is a different story.
            if (candidate.tickers, candidate.facts) != (
                item.tickers,
                item.facts,
            ):
                continue
            edits = word_edits(candidate.text, item.text)
            if edits > self._cfg.near_max_word_edits:
                continue
            rank = (distance, edits, candidate.order)
            if best is None or rank < best[0]:
                best = (rank, candidate)
        if best is None:
            return None
        (distance, edits, _), candidate = best
        return candidate, distance, edits

    async def check(self, item: DedupItem) -> DedupMatch | None:
        """Checks one item and indexes it when it's unique.

        Checking the same item again gives the same answer (it never
        matches itself), so a feed date can be re-run.

        Args:
            item: The item.

        Returns:
            The earlier item it copies, or None when it's unique.
        """
        features = self._features(item)
        indexed = features.indexed
        original = await self._level_hit(features.url_key, indexed)
        if original is not None:
            return self._match(original, indexed, "url", "L0")
        original = await self._level_hit(features.exact_key, indexed)
        if original is not None:
            return self._match(original, indexed, "exact", "L1")
        near = await self._near_hit(features)
        if near is not None:
            original, distance, edits = near
            match = self._match(original, indexed, "near", "L2")
            return dataclasses.replace(
                match, score=float(distance), word_edits=edits
            )
        await self._add(features)
        return None

    async def _add(self, features: _Features) -> None:
        level_keys = [features.exact_key]
        if features.url_key is not None:
            level_keys.append(features.url_key)
        await self._index.index(
            features.indexed, level_keys, features.band_keys
        )

    async def check_batch(
        self, items: Sequence[DedupItem]
    ) -> list[DedupMatch | None]:
        """Checks items in the given order (callers sort them first).

        Args:
            items: The items, earliest first.

        Returns:
            One result per item, in the same order.
        """
        return [await self.check(item) for item in items]

    async def index_unique(self, items: Sequence[DedupItem]) -> None:
        """Re-indexes items already known to be unique (warm-up).

        Args:
            items: Items the rule run stored as unique.
        """
        for item in items:
            await self._add(self._features(item))

    async def mark_day(self, day: datetime.date) -> None:
        """Records that every unique item of ``day`` is indexed."""
        await self._index.mark_day(day)

    async def has_day(self, day: datetime.date) -> bool:
        """True when ``day`` is in the index."""
        return await self._index.has_day(day)
