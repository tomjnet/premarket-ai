"""Long-term memory: each user's watchlist (LangGraph Store on Postgres).

The store lives in the ``memory`` schema, one namespace per user,
``("users", <username>)``, and one document per user, ``watchlist``:

- ``tickers``: up to 25 tickers the user follows (checked against the SEC
  ticker registry when it has been downloaded);
- ``sectors``: GICS sectors of the lab universe the user follows (their
  preference for the brief: those sectors come first).

What uses it:

- ``GET/PUT /me/watchlist``;
- the brief page ("Your watchlist" first);
- the chat agents ("my watchlist" means these tickers);
- the verification worker: a FAKE or MISLEADING verdict for a ticker on
  anyone's watchlist goes to an analyst (the human-in-the-loop policy).

Redis would lose it on a restart; Postgres is the source of truth for
anything a user saved.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
import contextlib
import dataclasses
import re
from typing import Any, Protocol

from langgraph.store import base as store_base
from langgraph.store.postgres import aio as pg_store
from psycopg import rows
from psycopg_pool import AsyncConnectionPool

from ai_api import config

NAMESPACE = "users"
WATCHLIST_KEY = "watchlist"
MAX_TICKERS = 25
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
# Every user's watchlist is read at once (the worker's watchlist rule).
_MAX_USERS = 10_000


class WatchlistError(ValueError):
    """A ticker or sector isn't valid."""


@dataclasses.dataclass(frozen=True)
class Watchlist:
    """What a user follows.

    Attributes:
        tickers: Tickers, in the order the user gave them.
        sectors: GICS sectors.
    """

    tickers: tuple[str, ...] = ()
    sectors: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        """The stored document."""
        return {"tickers": list(self.tickers), "sectors": list(self.sectors)}

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> Watchlist:
        """The watchlist of a stored document (empty when there is none)."""
        if not data:
            return cls()
        return cls(
            tuple(str(t) for t in data.get("tickers", ())),
            tuple(str(s) for s in data.get("sectors", ())),
        )


def normalize_tickers(raw: Iterable[str]) -> tuple[str, ...]:
    """Upper-cased, de-duplicated tickers (order kept).

    Args:
        raw: The tickers as the user typed them.

    Returns:
        The tickers.

    Raises:
        WatchlistError: A ticker has the wrong form, or there are more than
            ``MAX_TICKERS``.
    """
    found: list[str] = []
    for value in raw:
        ticker = value.strip().upper()
        if not _TICKER.match(ticker):
            raise WatchlistError(f"Not a ticker: {value[:20]!r}")
        if ticker not in found:
            found.append(ticker)
    if len(found) > MAX_TICKERS:
        raise WatchlistError(f"At most {MAX_TICKERS} tickers")
    return tuple(found)


def normalize_sectors(
    raw: Iterable[str], known: Iterable[str]
) -> tuple[str, ...]:
    """The sectors, each one of ``known`` (order kept, no repeats).

    Raises:
        WatchlistError: A sector isn't a sector of the lab universe.
    """
    allowed = set(known)
    found: list[str] = []
    for value in raw:
        sector = value.strip()
        if sector not in allowed:
            raise WatchlistError(f"Unknown sector: {sector[:60]!r}")
        if sector not in found:
            found.append(sector)
    return tuple(found)


class Memory(Protocol):
    """Users' watchlists (``StoreMemory``)."""

    async def watchlist(self, user: str) -> Watchlist:
        """The user's watchlist (empty when never saved)."""
        ...

    async def save_watchlist(self, user: str, watchlist: Watchlist) -> None:
        """Replaces the user's watchlist."""
        ...

    async def watched_tickers(self) -> frozenset[str]:
        """Every ticker on anyone's watchlist."""
        ...


class StoreMemory:
    """``Memory`` over a LangGraph store (Postgres in the stack)."""

    def __init__(self, store: store_base.BaseStore) -> None:
        """Uses ``store`` (its async methods)."""
        self._store = store

    async def watchlist(self, user: str) -> Watchlist:
        """See ``Memory``."""
        item = await self._store.aget((NAMESPACE, user), WATCHLIST_KEY)
        return Watchlist.from_json(None if item is None else item.value)

    async def save_watchlist(self, user: str, watchlist: Watchlist) -> None:
        """See ``Memory``."""
        await self._store.aput(
            (NAMESPACE, user), WATCHLIST_KEY, watchlist.to_json(), index=False
        )

    async def watched_tickers(self) -> frozenset[str]:
        """See ``Memory``."""
        found = await self._store.asearch((NAMESPACE,), limit=_MAX_USERS)
        tickers: set[str] = set()
        for item in found:
            if item.key == WATCHLIST_KEY:
                tickers.update(Watchlist.from_json(item.value).tickers)
        return frozenset(tickers)


def store_pool(
    database: config.Database, application: str, max_size: int = 4
) -> AsyncConnectionPool:
    """A pool for the store: its tables in ``memory``, dict rows.

    Args:
        database: The role to connect as.
        application: ``application_name`` in pg_stat_activity.
        max_size: Connections at most.

    Returns:
        The pool (not opened yet).
    """
    return AsyncConnectionPool(
        database.dsn(search_path="memory", application=application),
        min_size=1,
        max_size=max_size,
        timeout=5,
        check=AsyncConnectionPool.check_connection,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": rows.dict_row,
        },
    )


@contextlib.asynccontextmanager
async def open_memory(
    database: config.Database, application: str
) -> AsyncIterator[StoreMemory]:
    """The store over its own pool, closed on exit.

    Args:
        database: The role to connect as.
        application: ``application_name`` in pg_stat_activity.

    Yields:
        The memory.
    """
    pool = store_pool(database, application)
    # Like the API's main pool: don't block startup on the database.
    await pool.open(wait=False)
    try:
        yield StoreMemory(pg_store.AsyncPostgresStore(pool))
    finally:
        await pool.close()
