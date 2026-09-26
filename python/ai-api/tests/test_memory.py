"""Long-term memory: watchlists in the LangGraph store."""

import asyncio

from langgraph.store import memory as lg_memory
import pytest

from ai_api import memory
from ai_api.verify import graph
from ai_api.worker import app as worker_app


def test_tickers_and_sectors_are_normalized():
    assert memory.normalize_tickers([" aapl", "BRK.B", "AAPL"]) == (
        "AAPL",
        "BRK.B",
    )
    with pytest.raises(memory.WatchlistError):
        memory.normalize_tickers(["AAPL; DROP"])
    with pytest.raises(memory.WatchlistError):
        memory.normalize_tickers([f"T{i}" for i in range(26)])
    assert memory.normalize_sectors(
        ["Energy", "Energy"], ["Energy", "Financials"]
    ) == ("Energy",)
    with pytest.raises(memory.WatchlistError):
        memory.normalize_sectors(["Crypto"], ["Energy"])


def test_watchlists_per_user_and_every_watched_ticker():
    mem = memory.StoreMemory(lg_memory.InMemoryStore())

    async def run():
        empty = await mem.watchlist("trader1")
        await mem.save_watchlist("trader1", memory.Watchlist(("AAPL",), ()))
        await mem.save_watchlist(
            "analyst1", memory.Watchlist(("MSFT", "AAPL"), ("Energy",))
        )
        return (
            empty,
            await mem.watchlist("analyst1"),
            await mem.watched_tickers(),
        )

    empty, analyst, watched = asyncio.run(run())
    assert empty == memory.Watchlist()
    assert analyst.sectors == ("Energy",)
    assert watched == {"AAPL", "MSFT"}


class _CountingMemory:
    def __init__(self):
        self.reads = 0

    async def watched_tickers(self):
        self.reads += 1
        return frozenset({"AAPL"})


def test_the_worker_reads_watchlists_at_most_once_a_minute():
    source = _CountingMemory()
    watched = worker_app.WatchedTickers(source, ttl_s=60)

    async def run():
        return await watched(), await watched()

    assert asyncio.run(run()) == (frozenset({"AAPL"}), frozenset({"AAPL"}))
    assert source.reads == 1


def test_the_graph_rule_tolerates_a_missing_store():
    async def broken():
        raise ConnectionError("store down")

    async def aapl():
        return frozenset({"AAPL"})

    assert not asyncio.run(graph._on_watchlist(graph.Deps(repo=None), ["AAPL"]))
    down = graph.Deps(repo=None, watched=broken)
    assert not asyncio.run(graph._on_watchlist(down, ["AAPL"]))
    watching = graph.Deps(repo=None, watched=aapl)
    assert asyncio.run(graph._on_watchlist(watching, ["MSFT", "AAPL"]))
    assert not asyncio.run(graph._on_watchlist(watching, ["MSFT"]))
