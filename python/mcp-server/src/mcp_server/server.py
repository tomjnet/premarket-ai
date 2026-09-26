"""The MCP server: FastMCP over streamable HTTP, read-only tools.

Tools (every one read-only; there are no write tools anywhere):

==========================  ==============================================
``lookup_company``          SEC ticker registry + the lab universe
``get_source_reputation``   the source reputation table
``search_news``             the trusted corpus (vector store)
``get_verification``        an item's verdict and evidence
``web_search``              SearXNG (counted and linked, never stored)
``fetch_url``               one page as text (SSRF-protected, discarded)
``get_price_history``       daily closes (yfinance, lab only)
==========================  ==============================================

(``get_brief`` arrives with the brief in increment 5.)

Every client sends the service token (``Authorization: Bearer ...``,
MCP_SERVICE_TOKEN), not a user's JWT. The server is stateless (each HTTP
request stands alone), so ``ai-worker`` replicas can open a session per
item. Host headers are checked against MCP_ALLOWED_HOSTS (DNS rebinding).
``GET /healthz`` needs no token.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
import contextlib
import dataclasses
import datetime
import hmac
import json
import logging
from typing import Any

import httpx
from mcp import types as mcp_types
from mcp.server import fastmcp
from mcp.server import transport_security
from psycopg_pool import AsyncConnectionPool
from redis import asyncio as aioredis
from starlette import requests
from starlette import responses

import mcp_server
from mcp_server import cache
from mcp_server import config
from mcp_server import corpus
from mcp_server import fetch
from mcp_server import prices
from mcp_server import store
from mcp_server import web

_log = logging.getLogger(__name__)
_READ_ONLY = mcp_types.ToolAnnotations(readOnlyHint=True, openWorldHint=False)
_OPEN_WORLD = mcp_types.ToolAnnotations(readOnlyHint=True, openWorldHint=True)
_OPEN_PATHS = frozenset({"/healthz"})


@dataclasses.dataclass
class Services:
    """What the tools use (opened at startup).

    Attributes:
        lookups: Registry, reputation and verdict reads.
        cache: The Redis tool cache and rate limits.
        corpus: Vector search.
        web: SearXNG.
        fetcher: The page fetcher.
        prices: The price history function.
        settings: The settings.
    """

    lookups: store.Lookups
    cache: cache.ToolCache
    corpus: corpus.Corpus
    web: web.WebSearch
    fetcher: fetch.Fetcher
    prices: Callable[[str, int], Awaitable[dict[str, Any]]]
    settings: config.Settings


class _Holder:
    """The services, set by the app's lifespan (or by tests)."""

    def __init__(self, services: Services | None = None) -> None:
        self.services = services

    def get(self) -> Services:
        if self.services is None:
            raise RuntimeError("the MCP server hasn't started")
        return self.services


def build_server(settings: config.Settings, holder: _Holder) -> fastmcp.FastMCP:
    """The FastMCP server with every tool (closed over ``holder``)."""
    server = fastmcp.FastMCP(
        name="premarket-ai",
        instructions=(
            "Read-only tools over premarket-ai's data: the SEC ticker "
            "registry, source reputations, the trusted corpus of SEC filings "
            "and Fed/SEC releases, verdicts of vendor news, live web search, "
            "page fetches and price history. Vendor news is synthetic lab "
            "data. Nothing here gives investment advice."
        ),
        stateless_http=True,
        json_response=True,
        transport_security=transport_security.TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(settings.allowed_hosts),
            allowed_origins=["http://localhost:*", "http://127.0.0.1:*"],
        ),
    )

    @server.tool(annotations=_READ_ONLY)
    async def lookup_company(query: str) -> dict[str, Any]:
        """Find a US-listed company in the SEC ticker registry.

        Args:
            query: A ticker in capitals (AAPL, BRK.B) or part of a name.
        """
        services = holder.get()
        return await services.cache.cached(
            "lookup_company",
            {"query": query},
            cache.LOOKUP_TTL_S,
            lambda: services.lookups.lookup_company(query),
        )

    @server.tool(annotations=_READ_ONLY)
    async def get_source_reputation(domain: str) -> dict[str, Any]:
        """A news source's reputation tier (trusted, neutral, low, blocked).

        Args:
            domain: The source's host name.
        """
        return await holder.get().lookups.source_reputation(domain)

    @server.tool(annotations=_READ_ONLY)
    async def search_news(
        query: str,
        date: str | None = None,
        ticker: str | None = None,
        days: int = 7,
        k: int = 8,
    ) -> dict[str, Any]:
        """Search the trusted corpus: SEC 8-K filings, press releases, facts.

        Args:
            query: What to look for.
            date: YYYY-MM-DD: only documents from the days before it.
            ticker: Only this company's documents.
            days: The window before ``date`` (default 7).
            k: How many results (at most 20).
        """
        services = holder.get()
        day = None if date is None else datetime.date.fromisoformat(date)
        return await services.corpus.search(query, day, ticker, days, k)

    @server.tool(annotations=_READ_ONLY)
    async def get_verification(vendor_item_id: str) -> dict[str, Any]:
        """The AI verdict of a vendor news item, with its evidence.

        Args:
            vendor_item_id: The vendor's id, like VND-20260924-012.
        """
        return await holder.get().lookups.verification(vendor_item_id)

    @server.tool(annotations=_OPEN_WORLD)
    async def web_search(query: str, max_results: int = 8) -> dict[str, Any]:
        """Search the live web (titles, links and snippets only).

        Args:
            query: The search text.
            max_results: How many results (at most 10).
        """
        services = holder.get()

        async def compute() -> dict[str, Any]:
            await services.cache.limit("web", services.settings.web_per_minute)
            return await services.web.search(query, max_results)

        return await services.cache.cached(
            "web_search",
            {"query": query, "max": max_results},
            cache.WEB_TTL_S,
            compute,
        )

    @server.tool(annotations=_OPEN_WORLD)
    async def fetch_url(url: str) -> dict[str, Any]:
        """Fetch one public web page as plain text (checked, not archived).

        Args:
            url: An absolute http(s) URL.
        """
        services = holder.get()
        return await services.cache.cached(
            "fetch_url",
            {"url": url},
            cache.FETCH_TTL_S,
            lambda: services.fetcher.fetch(url),
        )

    @server.tool(annotations=_OPEN_WORLD)
    async def get_price_history(ticker: str, days: int = 10) -> dict[str, Any]:
        """Daily closing prices and daily changes of a US ticker.

        Args:
            ticker: The ticker (AAPL, BRK.B).
            days: Trading days (at most 60).
        """
        services = holder.get()

        async def compute() -> dict[str, Any]:
            await services.cache.limit(
                "prices", services.settings.prices_per_minute
            )
            return await services.prices(ticker, days)

        return await services.cache.cached(
            "get_price_history",
            {"ticker": ticker.upper(), "days": days},
            cache.PRICES_TTL_S,
            compute,
        )

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(request: requests.Request) -> responses.Response:
        del request
        return responses.PlainTextResponse("ok")

    return server


class BearerAuth:
    """ASGI middleware: every request but /healthz needs the service token."""

    def __init__(self, app: Any, token: str) -> None:
        """Wraps ``app``."""
        self._app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """Answers 401 without the right token."""
        if scope["type"] == "http" and scope["path"] not in _OPEN_PATHS:
            given = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(given, self._expected):
                body = json.dumps({"detail": "Not authenticated"}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"www-authenticate", b"Bearer"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self._app(scope, receive, send)


@contextlib.asynccontextmanager
async def open_services(settings: config.Settings) -> AsyncIterator[Services]:
    """Opens the pool, Redis and the HTTP client for the server's life."""
    pool = AsyncConnectionPool(
        settings.dsn(),
        min_size=1,
        max_size=5,
        timeout=5,
        check=AsyncConnectionPool.check_connection,
        open=False,
        kwargs={"autocommit": True},
    )
    await pool.open(wait=False)
    redis = aioredis.Redis(
        host=settings.redis_host,
        password=settings.redis_password,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    http = httpx.AsyncClient(follow_redirects=False)
    try:
        yield Services(
            lookups=store.Lookups(
                store.PostgresStore(pool),
                store.load_universe(settings.config_dir),
            ),
            cache=cache.ToolCache(redis),
            corpus=corpus.Corpus(settings, http),
            web=web.WebSearch(settings.searxng_url, http),
            fetcher=fetch.Fetcher(http, settings.fetch_max_bytes),
            prices=prices.price_history,
            settings=settings,
        )
    finally:
        await http.aclose()
        await redis.aclose()
        await pool.close()


def create_app(
    settings: config.Settings, services: Services | None = None
) -> Any:
    """The ASGI app: the MCP endpoint at ``/mcp``, behind the token.

    Args:
        settings: The settings.
        services: Ready-made services (tests); None opens real ones.

    Returns:
        The Starlette app, wrapped in ``BearerAuth``.
    """
    holder = _Holder(services)
    server = build_server(settings, holder)
    app = server.streamable_http_app()
    inner = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(started: Any) -> AsyncIterator[None]:
        if services is not None:
            async with inner(started):
                yield
            return
        async with open_services(settings) as opened:
            holder.services = opened
            _log.info("mcp-server %s ready", mcp_server.__version__)
            async with inner(started):
                yield

    app.router.lifespan_context = lifespan
    app.add_middleware(BearerAuth, token=settings.token)
    return app
