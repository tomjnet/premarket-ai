"""The ai-api FastAPI application.

Run by uvicorn as a factory: ``uvicorn ai_api.app:create_app --factory``.
The API is never published: browsers reach it only through the edge proxy
(``/api/*`` with the prefix stripped), which adds rate limits and the site's
security headers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
import contextlib
import logging
import os

import fastapi
from psycopg_pool import AsyncConnectionPool
from redis import asyncio as aioredis

import ai_api
from ai_api import config
from ai_api import deps
from ai_api import news
from ai_api import sessions
from ai_api import users
from ai_api.routes import auth
from ai_api.routes import health
from ai_api.routes import news as news_routes

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

    try:
        yield deps.Services(
            settings=settings,
            users=users.PostgresUserStore(pool),
            news=news.PostgresNewsStore(pool),
            sessions=sessions.SessionStore(
                redis,
                ttl_s=settings.refresh_token_ttl_s,
                grace_s=settings.refresh_grace_s,
                max_failures=settings.login_max_failures,
                lockout_s=settings.login_lockout_s,
            ),
            ping=ping,
        )
    finally:
        await pool.close()
        await redis.aclose()


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
        async with open_services(settings) as opened:
            app.state.services = opened
            yield

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
        response = await call_next(request)
        # Swagger UI (EXPOSE_DOCS=true, local debugging only) needs scripts.
        swagger = docs and request.url.path == "/docs"
        for name, value in _SECURITY_HEADERS.items():
            if not (swagger and name == "Content-Security-Policy"):
                response.headers.setdefault(name, value)
        return response

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(news_routes.router)
    return app
