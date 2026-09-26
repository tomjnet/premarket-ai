"""Lookups, the cache, web search, prices and the MCP app end to end."""

import asyncio
import datetime
import os
import pathlib

import fakeredis
import httpx
import pytest
from starlette import testclient

from mcp_server import cache
from mcp_server import config
from mcp_server import prices
from mcp_server import server
from mcp_server import store
from mcp_server import web

_CONFIG = pathlib.Path(
    os.environ.get("PREMARKET_CONFIG_DIR")
    or pathlib.Path(__file__).resolve().parents[2] / "config"
)
_TOKEN = "t" * 40


class FakeStore:
    """Two registry rows, reputations, one verified item."""

    async def registry_size(self):
        """Two tickers."""
        return 2

    async def company(self, ticker):
        """A registry row."""
        rows = {
            "AAPL": {"ticker": "AAPL", "cik": 320193, "title": "Apple Inc."},
            "BRK-B": {"ticker": "BRK-B", "cik": 1067983, "title": "BERKSHIRE"},
        }
        return rows.get(ticker)

    async def companies_named(self, name):
        """Rows whose name contains ``name``."""
        if "apple" in name.lower():
            return [{"ticker": "AAPL", "cik": 320193, "title": "Apple Inc."}]
        return []

    async def reputation(self, domain):
        """The one listed domain."""
        if domain == "vendornews.example":
            return {
                "domain": domain,
                "tier": "trusted",
                "reputation": 0.9,
                "note": "wire",
            }
        return None

    async def verification(self, vendor_item_id):
        """One verified item."""
        if vendor_item_id != "VND-20260924-001":
            return None
        return {
            "news_id": 11,
            "feed_date": datetime.date(2026, 9, 24),
            "headline": "[SYNTHETIC] Apple raises dividend",
            "source_domain": "wire.vendornews.example",
            "tickers": ["AAPL"],
            "status": "DONE",
            "verdict": "VERIFIED",
            "confidence": 0.91,
            "reason_codes": [],
            "rationale": "Trusted wire [E1].",
            "review_status": None,
            "rule_verdict": "VERIFIED",
            "judge_verdict": "VERIFIED",
            "judge_model": "main-gpu4gb",
            "escalated": False,
            "impact": "medium",
            "verified_at": datetime.datetime(
                2026, 9, 24, 10, tzinfo=datetime.UTC
            ),
        }

    async def evidence(self, news_id):
        """Its one piece of evidence."""
        return [
            {
                "seq": 1,
                "check": "source",
                "code": None,
                "message": "trusted",
                "url": None,
            }
        ]


def _lookups():
    return store.Lookups(FakeStore(), store.load_universe(_CONFIG))


def test_ticker_lookup_with_the_universe_rank():
    found = asyncio.run(_lookups().lookup_company("AAPL"))
    assert found["found"] and found["name"] == "Apple Inc."
    assert found["rank"] == 2 and found["in_universe"]
    brk = asyncio.run(_lookups().lookup_company("BRK.B"))
    assert brk["found"] and brk["cik"] == 1067983
    missing = asyncio.run(_lookups().lookup_company("QVXH"))
    assert (missing["found"], missing["registry"]) == (False, True)


def test_name_lookup():
    found = asyncio.run(_lookups().lookup_company("Apple"))
    assert found["matches"][0]["ticker"] == "AAPL"
    assert found["matches"][0]["in_universe"]


def test_reputation_of_a_subdomain():
    found = asyncio.run(_lookups().source_reputation("Wire.VendorNews.example"))
    assert (found["tier"], found["listed_as"]) == (
        "trusted",
        "vendornews.example",
    )
    unknown = asyncio.run(_lookups().source_reputation("reuters-news.test"))
    assert unknown["tier"] == "unknown"


def test_verification_with_evidence():
    found = asyncio.run(_lookups().verification("vnd-20260924-001"))
    assert found["verdict"] == "VERIFIED"
    assert found["evidence"] == [{"E1": "trusted", "check": "source"}]
    assert asyncio.run(_lookups().verification("DROP TABLE"))["found"] is False


def test_cache_and_rate_limit():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    tools = cache.ToolCache(redis)
    calls = []

    async def compute():
        calls.append(1)
        return {"n": len(calls)}

    async def run():
        first = await tools.cached("t", {"a": 1}, 60, compute)
        second = await tools.cached("t", {"a": 1}, 60, compute)
        await tools.limit("web", 2)
        await tools.limit("web", 2)
        with pytest.raises(cache.RateLimitedError):
            await tools.limit("web", 2)
        return first, second

    assert asyncio.run(run()) == ({"n": 1}, {"n": 1})


def test_web_search_results():
    def handler(request):
        assert request.url.params["format"] == "json"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://www.reuters.com/a",
                        "title": "Apple raises dividend",
                        "content": "Apple  said...",
                    },
                    {"url": "javascript:alert(1)", "title": "x"},
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    found = asyncio.run(
        web.WebSearch("http://searxng:8080", client).search("q")
    )
    assert found["results"] == [
        {
            "title": "Apple raises dividend",
            "url": "https://www.reuters.com/a",
            "domain": "reuters.com",
            "snippet": "Apple said...",
            "published": None,
        }
    ]


def test_prices():
    assert prices.yahoo_symbol("brk.b") == "BRK-B"
    with pytest.raises(prices.PriceError):
        prices.yahoo_symbol("AAPL; rm")
    rows = prices.closes_with_changes([("d1", 100.0), ("d2", 110.0)])
    assert rows[1]["change_pct"] == 10.0


def _app():
    settings = config.Settings(
        token=_TOKEN, allowed_hosts=("testserver",), config_dir=_CONFIG
    )
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: None))
    services = server.Services(
        lookups=_lookups(),
        cache=cache.ToolCache(redis),
        corpus=None,
        web=web.WebSearch("http://searxng:8080", http),
        fetcher=None,
        prices=prices.price_history,
        settings=settings,
    )
    return server.create_app(settings, services)


_HEADERS = {
    "Authorization": f"Bearer {_TOKEN}",
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _rpc(client, method, params, ident=1):
    response = client.post(
        "/mcp",
        headers=_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": ident,
            "method": method,
            "params": params,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_the_mcp_endpoint_needs_the_token_and_lists_read_only_tools():
    with testclient.TestClient(_app()) as client:
        assert client.get("/healthz").text == "ok"
        denied = client.post("/mcp", json={})
        assert denied.status_code == 401
        wrong = client.post(
            "/mcp", headers={"Authorization": "Bearer nope"}, json={}
        )
        assert wrong.status_code == 401
        _rpc(
            client,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        tools = _rpc(client, "tools/list", {}, 2)["result"]["tools"]
        names = {tool["name"] for tool in tools}
        assert names == {
            "lookup_company",
            "get_source_reputation",
            "search_news",
            "get_verification",
            "web_search",
            "fetch_url",
            "get_price_history",
        }
        assert all(t["annotations"]["readOnlyHint"] for t in tools)
        called = _rpc(
            client,
            "tools/call",
            {"name": "lookup_company", "arguments": {"query": "AAPL"}},
            3,
        )["result"]
        assert called["structuredContent"]["name"] == "Apple Inc."


def test_a_foreign_host_header_is_refused():
    with testclient.TestClient(_app(), base_url="http://evil.example") as c:
        response = c.post("/mcp", headers=_HEADERS, json={})
        assert response.status_code in (400, 421)
