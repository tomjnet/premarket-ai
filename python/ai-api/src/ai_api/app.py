"""The ai-api FastAPI application.

Run by uvicorn as a factory: ``uvicorn ai_api.app:create_app --factory``.
The API is never published: browsers reach it only through the edge proxy
(``/api/*`` with the prefix stripped), which adds rate limits and the site's
security headers.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
import contextlib
import datetime
import logging
import os
import time
from typing import Any

import fastapi
from psycopg_pool import AsyncConnectionPool
from redis import asyncio as aioredis

import ai_api
from ai_api import admin
from ai_api import alerts
from ai_api import briefs
from ai_api import config
from ai_api import deps
from ai_api import memory as memory_lib
from ai_api import news
from ai_api import schedule
from ai_api import scorecard
from ai_api import sessions
from ai_api import telemetry
from ai_api import users
from ai_api import verdicts
from ai_api.agents import skills
from ai_api.agents import supervisor
from ai_api.guard import llama_guard
from ai_api.llm import budget
from ai_api.llm import factory
from ai_api.llm import tracing
from ai_api.rag import ask
from ai_api.rag import cache
from ai_api.rag import rerank
from ai_api.rag import store
from ai_api.rag import universe
from ai_api.routes import admin as admin_routes
from ai_api.routes import alerts as alert_routes
from ai_api.routes import auth
from ai_api.routes import briefs as brief_routes
from ai_api.routes import chat
from ai_api.routes import health
from ai_api.routes import me
from ai_api.routes import news as news_routes
from ai_api.routes import review
from ai_api.routes import runs
from ai_api.routes import vendor
from ai_api.verify import events
from ai_api.worker import queue

_log = logging.getLogger(__name__)

# Every API response: JSON that must never be cached, sniffed, framed or
# rendered as a page.
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _vendor_lookup(
    news_store: news.NewsStore,
) -> Callable[[datetime.date, Sequence[str]], Awaitable[list[dict[str, Any]]]]:
    """The day's unique, summarized items for some tickers (chat)."""

    async def lookup(
        day: datetime.date, tickers: Sequence[str]
    ) -> list[dict[str, Any]]:
        found: dict[int, dict[str, Any]] = {}
        for ticker in tickers[:3]:
            rows = await news_store.items(news.NewsQuery(day, ticker=ticker))
            for row in rows[:2]:
                found.setdefault(row["id"], row)
        return list(found.values())

    return lookup


def _team(
    settings: config.Settings, tracer: tracing.Tracer
) -> supervisor.Supervisor | None:
    """The chat's multi-agent team, when the MCP server is configured."""
    llm = settings.llm
    if llm is None or not settings.chat_agents:
        return None
    if not settings.mcp_token:
        _log.warning("MCP_SERVICE_TOKEN isn't set: chat agents are off")
        return None
    from langchain_mcp_adapters import client as mcp_client  # noqa: PLC0415

    mcp = mcp_client.MultiServerMCPClient(
        {
            supervisor.SERVER: {
                "transport": "streamable_http",
                "url": settings.mcp_url,
                "headers": {"Authorization": f"Bearer {settings.mcp_token}"},
                "timeout": 30,
                "sse_read_timeout": 120,
            }
        }
    )
    return supervisor.Supervisor(
        factory.chat_model(llm, max_tokens=400),
        skills.Library.load(settings.skills_dir),
        tracer,
        mcp=mcp,
        max_tool_calls=settings.agent_max_tool_calls,
    )


async def _cache(
    settings: config.Settings, embeddings: store.PrefixedEmbeddings
) -> cache.AnswerCache | None:
    """The semantic answer cache (off when Redis can't create it)."""
    llm = settings.llm
    if llm is None or not settings.chat_cache:
        return None
    url = queue.redis_url(settings.redis_host, settings.redis_password)
    try:
        backend = await asyncio.to_thread(
            cache.build_backend,
            url,
            llm.embed_dims,
            settings.chat_cache_ttl_s,
            settings.chat_cache_distance,
        )
    except Exception as e:  # noqa: BLE001 - chat works without a cache.
        _log.warning("semantic cache off: %r", e)
        return None
    return cache.AnswerCache(backend, embeddings, settings.chat_cache_ttl_s)


async def build_ask(
    settings: config.Settings,
    news_store: news.NewsStore,
    memory: memory_lib.Memory | None = None,
    connect: store.Connect | None = None,
) -> tuple[ask.AskService | None, rerank.Reranker | None]:
    """The "Ask the News" service when the LLM and RAG are configured.

    Args:
        settings: The settings.
        news_store: The day's items (vendor sources of an answer).
        memory: Users' watchlists, or None.
        connect: Database connections (the pgvector store reads
            ``ai.chunk`` through them).

    Returns:
        The service and its reranker (to close), or (None, None).
    """
    llm = settings.llm
    if llm is None or settings.rag is None:
        _log.warning("LLM_GATEWAY_KEY isn't set: Ask the News is off")
        return None, None
    embeddings = store.PrefixedEmbeddings(
        factory.embeddings(llm), llm.query_prefix, llm.document_prefix
    )
    reranker = rerank.Reranker(settings.rag.reranker_url)
    guard = llama_guard.Guard(
        factory.chat_model(llm, model=llm.guard_model, max_tokens=20)
        if settings.llama_guard
        else None
    )
    tracer = tracing.Tracer(settings.tracing)
    service = ask.AskService(
        store=store.open_store(
            settings.rag,
            embeddings,
            llm.embed_model,
            llm.embed_dims,
            connect=connect,
        ),
        reranker=reranker,
        model=factory.chat_model(llm, max_tokens=600),
        tracer=tracer,
        cfg=settings.rag,
        members=universe.load(settings.config_dir),
        vendor_lookup=_vendor_lookup(news_store),
        model_name=llm.main_model,
        guard=guard,
        team=_team(settings, tracer),
        cache=await _cache(settings, embeddings),
        memory=memory,
    )
    return service, reranker


def _summarizer(settings: config.Settings) -> scorecard.Summarizer | None:
    """The weekly vendor summary's writer (the local main model)."""
    llm = settings.llm
    if llm is None:
        return None
    try:
        skill = skills.Library.load(settings.skills_dir).body(
            "vendor-scorecard"
        )
    except OSError as e:
        _log.warning("skills unreadable: %r", e)
        return None
    if skill is None:
        _log.warning("the vendor-scorecard skill is missing")
        return None
    return scorecard.Summarizer(
        factory.chat_model(llm, max_tokens=400), llm.main_model, skill
    )


def _sectors(settings: config.Settings) -> tuple[str, ...]:
    try:
        return tuple(universe.sectors(universe.load(settings.config_dir)))
    except OSError as e:
        _log.warning("universe.yaml unreadable: %r", e)
        return ()


@contextlib.asynccontextmanager
async def open_services(
    settings: config.Settings,
) -> AsyncIterator[deps.Services]:
    """Opens the database pool and the Redis client for the app's lifetime.

    Args:
        settings: The runtime settings.

    Yields:
        The services; connections are closed on exit.
    """
    pool = AsyncConnectionPool(
        settings.database.dsn(),
        min_size=1,
        max_size=10,
        timeout=5,
        # Checked on every checkout: after a database restart the pool drops
        # dead connections instead of failing a request with them.
        check=AsyncConnectionPool.check_connection,
        open=False,
        kwargs={"autocommit": True},
    )
    # Don't block startup on the database: /health reports it instead.
    await pool.open(wait=False)
    redis = aioredis.Redis(
        host=settings.redis_host,
        password=settings.redis_password,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )

    async def ping() -> None:
        async with pool.connection(timeout=3) as conn:
            await conn.execute("SELECT 1")
        await redis.ping()

    news_store = news.PostgresNewsStore(pool)
    jobs = queue.Queue(
        queue.make_broker(settings.redis_host, settings.redis_password)
    )
    await jobs.start()
    async with contextlib.AsyncExitStack() as stack:
        # Closed in reverse order: the queue, the pools, then Redis.
        stack.push_async_callback(redis.aclose)
        stack.push_async_callback(pool.close)
        stack.push_async_callback(jobs.stop)
        memory = await stack.enter_async_context(
            memory_lib.open_memory(settings.database, "ai-api")
        )
        ask_service, reranker = await build_ask(
            settings, news_store, memory, pool.connection
        )
        administration = admin.PostgresAdmin(pool, redis)
        try:
            # Redis keeps nothing across a restart: the admin's cloud
            # switches come back from Postgres.
            await administration.restore()
        except Exception as e:  # noqa: BLE001 - the switches default to on.
            _log.warning("cloud switches not restored: %r", e)
        user_store = users.PostgresUserStore(pool)
        if reranker is not None:
            stack.push_async_callback(reranker.aclose)
        yield deps.Services(
            settings=settings,
            users=user_store,
            news=news_store,
            sessions=sessions.SessionStore(
                redis,
                ttl_s=settings.refresh_token_ttl_s,
                grace_s=settings.refresh_grace_s,
                max_failures=settings.login_max_failures,
                lockout_s=settings.login_lockout_s,
            ),
            ping=ping,
            ask=ask_service,
            chat_gate=chat.ChatGate(redis),
            verdicts=verdicts.PostgresVerdictStore(pool),
            queue=jobs,
            run_events=events.RunEvents(redis),
            briefs=briefs.PostgresBriefs(pool),
            brief_events=events.RunEvents(redis, prefix="brief"),
            memory=memory,
            sectors=_sectors(settings),
            alerts=alerts.Alerts(redis),
            budget=budget.CloudBudget(redis, settings.monthly_budget_usd),
            admin=administration,
            user_admin=user_store,
            scorecard=scorecard.PostgresScorecard(pool),
            summarizer=_summarizer(settings),
            cache=redis,
            schedule=schedule.PostgresSchedule(pool),
        )


def create_app(
    settings: config.Settings | None = None,
    services: deps.Services | None = None,
) -> fastapi.FastAPI:
    """Builds the application.

    Args:
        settings: The settings; None reads them from the environment.
        services: Ready-made services (tests); None opens real connections
            at startup.

    Returns:
        The FastAPI app.
    """
    if services is not None:
        settings = services.settings
    elif settings is None:
        settings = config.Settings.from_env(os.environ)

    @contextlib.asynccontextmanager
    async def lifespan(app: fastapi.FastAPI) -> AsyncIterator[None]:
        if services is not None:
            app.state.services = services
            yield
            return
        telemetry.setup("ai-api", os.environ)
        try:
            async with open_services(settings) as opened:
                app.state.services = opened
                yield
        finally:
            telemetry.shutdown()

    docs = settings.expose_docs
    app = fastapi.FastAPI(
        title="premarket-ai ai-api",
        version=ai_api.__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )

    @app.middleware("http")
    async def security_headers(
        request: fastapi.Request,
        call_next: Callable[[fastapi.Request], Awaitable[fastapi.Response]],
    ) -> fastapi.Response:
        started = time.monotonic()
        response = await call_next(request)
        # The route template (/news/{item_id}), never the raw path: ids and
        # query strings would make one series per request.
        route = getattr(request.scope.get("route"), "path", "unmatched")
        telemetry.record_http(
            route,
            request.method,
            response.status_code,
            time.monotonic() - started,
        )
        # Swagger UI (EXPOSE_DOCS=true, local debugging only) needs scripts.
        swagger = docs and request.url.path == "/docs"
        for name, value in _SECURITY_HEADERS.items():
            if not (swagger and name == "Content-Security-Policy"):
                response.headers.setdefault(name, value)
        return response

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(news_routes.router)
    app.include_router(chat.router)
    app.include_router(runs.router)
    app.include_router(review.router)
    app.include_router(brief_routes.router)
    app.include_router(me.router)
    app.include_router(alert_routes.router)
    app.include_router(vendor.router)
    app.include_router(admin_routes.router)
    return app
