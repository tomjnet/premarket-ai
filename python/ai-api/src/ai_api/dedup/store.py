"""The duplicate index in Redis: fast, temporary and rebuildable.

Keys (all expire after the window plus a day):

- ``dedup:url:{sha1}``: L0, canonical URL -> news id of the first copy.
- ``dedup:exact:{sha256}``: L1, normalized story -> news id.
- ``dedup:sim:{bands}:b{i}:{hex}``: L2, a set of news ids per SimHash band.
- ``dedup:item:{id}``: what a later check needs about an indexed item: its
  feed date and vendor id (to order items and apply the window), SimHash,
  tickers, key numbers and normalized text.
- ``dedup:day:{date}``: set once a feed date is in the index.

Only unique items are indexed. Postgres keeps the decisions
(``ai.duplicate_link``); losing Redis only means re-indexing the window.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import dataclasses
import datetime
import json

from redis import asyncio as aioredis


@dataclasses.dataclass(frozen=True)
class IndexedItem:
    """An item in the index.

    Attributes:
        news_id: The ``ai.news_item`` id.
        feed_date: The feed date it came in.
        vendor_item_id: The vendor's id, which orders items within a day.
        simhash: Its 64-bit SimHash.
        tickers: Its tickers, sorted.
        facts: Its key numbers (``extract_key_numbers``).
        text: Its normalized story text.
    """

    news_id: int
    feed_date: datetime.date
    vendor_item_id: str
    simhash: int
    tickers: tuple[str, ...]
    facts: tuple[str, ...]
    text: str

    @property
    def order(self) -> tuple[datetime.date, str]:
        """Earlier feed dates first, then the vendor's own sequence."""
        return (self.feed_date, self.vendor_item_id)


def url_key(digest: str) -> str:
    """The L0 key of a canonical URL's SHA-1."""
    return f"dedup:url:{digest}"


def exact_key(digest: str) -> str:
    """The L1 key of a normalized story's SHA-256."""
    return f"dedup:exact:{digest}"


def band_key(bands: int, index: int, value: int) -> str:
    """The L2 set of one band value (the band count keeps configs apart)."""
    return f"dedup:sim:{bands}:b{index}:{value:x}"


def _item_key(news_id: int) -> str:
    return f"dedup:item:{news_id}"


def _day_key(day: datetime.date) -> str:
    return f"dedup:day:{day.isoformat()}"


def _encode(item: IndexedItem) -> dict[str, str]:
    return {
        "feed_date": item.feed_date.isoformat(),
        "vendor_item_id": item.vendor_item_id,
        "simhash": f"{item.simhash:x}",
        "tickers": json.dumps(list(item.tickers)),
        "facts": json.dumps(list(item.facts)),
        "text": item.text,
    }


def _decode(news_id: int, data: dict[str, str]) -> IndexedItem | None:
    try:
        return IndexedItem(
            news_id=news_id,
            feed_date=datetime.date.fromisoformat(data["feed_date"]),
            vendor_item_id=data["vendor_item_id"],
            simhash=int(data["simhash"], 16),
            tickers=tuple(json.loads(data["tickers"])),
            facts=tuple(json.loads(data["facts"])),
            text=data["text"],
        )
    except (KeyError, ValueError):
        return None


class DedupStore:
    """Redis operations of the duplicate check."""

    def __init__(self, redis: aioredis.Redis, ttl_s: int) -> None:
        """Uses ``redis`` (decode_responses=True); keys live ``ttl_s``."""
        self._redis = redis
        self._ttl_s = ttl_s

    async def holder(self, key: str) -> int | None:
        """The news id stored under an L0/L1 key, or None."""
        value = await self._redis.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    async def band_members(self, keys: Sequence[str]) -> set[int]:
        """Every news id in the given band sets."""
        async with self._redis.pipeline(transaction=False) as pipe:
            for key in keys:
                pipe.smembers(key)
            results = await pipe.execute()
        return {int(member) for members in results for member in members}

    async def items(self, news_ids: Iterable[int]) -> dict[int, IndexedItem]:
        """The indexed items among ``news_ids`` (expired ones are left out)."""
        ids = list(news_ids)
        if not ids:
            return {}
        async with self._redis.pipeline(transaction=False) as pipe:
            for news_id in ids:
                pipe.hgetall(_item_key(news_id))
            results = await pipe.execute()
        found = {}
        for news_id, data in zip(ids, results, strict=True):
            item = _decode(news_id, data) if data else None
            if item is not None:
                found[news_id] = item
        return found

    async def index(
        self,
        item: IndexedItem,
        level_keys: Sequence[str],
        band_keys: Sequence[str],
    ) -> None:
        """Adds a unique item: its L0/L1 keys, L2 bands and details.

        The L0/L1 keys are overwritten: the check already found that no
        valid earlier item holds them (an expired, later or out-of-window
        holder loses its key).

        Args:
            item: The item.
            level_keys: Its L0 and L1 keys.
            band_keys: Its L2 band set keys.
        """
        ttl = self._ttl_s
        async with self._redis.pipeline(transaction=True) as pipe:
            for key in level_keys:
                pipe.set(key, item.news_id, ex=ttl)
            for key in band_keys:
                pipe.sadd(key, item.news_id)
                pipe.expire(key, ttl)
            pipe.hset(_item_key(item.news_id), mapping=_encode(item))
            pipe.expire(_item_key(item.news_id), ttl)
            await pipe.execute()

    async def mark_day(self, day: datetime.date) -> None:
        """Records that ``day`` is in the index."""
        await self._redis.set(_day_key(day), "1", ex=self._ttl_s)

    async def has_day(self, day: datetime.date) -> bool:
        """True when ``day`` was indexed and hasn't expired."""
        return bool(await self._redis.exists(_day_key(day)))
