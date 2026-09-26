"""FastAPI dependencies: services, client IP, origin check and roles."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import dataclasses
from typing import Annotated, Protocol

import fastapi

from ai_api import config
from ai_api import news
from ai_api import sessions
from ai_api import tokens
from ai_api import users
from ai_api import verdicts as verdicts_lib
from ai_api.rag import ask as ask_lib
from ai_api.verify import events as events_lib

NOT_AUTHENTICATED = "Not authenticated"
FORBIDDEN = "Forbidden"
# Sec-Fetch-Site values a same-site page or a non-browser client sends.
_TRUSTED_FETCH_SITES = frozenset({"same-origin", "none"})


class Jobs(Protocol):
    """Queues verification jobs (``worker.queue.Queue``)."""

    async def run_day(self, run_id: int) -> None:
        """Queues a verify run's coordinator."""
        ...

    async def resume(
        self, run_id: int, news_id: int, thread_id: str, decision: dict
    ) -> None:
        """Queues the resume of a graph waiting for review."""
        ...


class Gate(Protocol):
    """One chat question in flight per user (``routes.chat.ChatGate``)."""

    async def enter(self, user: str) -> bool:
        """True when the user had no question in flight."""
        ...

    async def leave(self, user: str) -> None:
        """Frees the user's slot."""
        ...


@dataclasses.dataclass(frozen=True)
class Services:
    """Everything the routes need, built once per process.

    Attributes:
        settings: The runtime settings.
        users: Users and the audit log.
        news: The news feed.
        sessions: Login sessions and throttling.
        ping: Raises if a backing service (database, Redis) is down.
        ask: "Ask the News"; None when the LLM isn't configured.
        chat_gate: The per-user chat lock.
        verdicts: Verify runs and the review queue (increment 4).
        queue: The job queue of the verification worker.
        run_events: Run progress (Redis Streams).
    """

    settings: config.Settings
    users: users.UserStore
    news: news.NewsStore
    sessions: sessions.SessionStore
    ping: Callable[[], Awaitable[None]]
    ask: ask_lib.AskService | None = None
    chat_gate: Gate | None = None
    verdicts: verdicts_lib.VerdictStore | None = None
    queue: Jobs | None = None
    run_events: events_lib.RunEvents | None = None


def get_services(request: fastapi.Request) -> Services:
    """Returns the services stored on the app at startup."""
    return request.app.state.services


ServicesDep = Annotated[Services, fastapi.Depends(get_services)]


def client_ip(request: fastapi.Request) -> str | None:
    """The caller's IP address, for the audit log.

    The API is only reachable through the edge proxy, which overwrites
    X-Real-IP; the header can't be forged from outside.
    """
    forwarded = request.headers.get("x-real-ip")
    if forwarded:
        return forwarded[:64]
    return None if request.client is None else request.client.host


def check_origin(request: fastapi.Request, services: ServicesDep) -> None:
    """Rejects cross-site calls to the cookie-based auth endpoints (CSRF).

    The refresh cookie is already ``SameSite=Strict``; this is the second
    layer. A browser always sends ``Origin`` on a POST and
    ``Sec-Fetch-Site`` on every request, so a page on another site is
    refused even if a browser ignored SameSite. Clients that send neither
    (curl, the smoke test) are not browsers and can't be tricked into a
    cross-site request.

    Raises:
        fastapi.HTTPException: 403 for a cross-site call.
    """
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site not in _TRUSTED_FETCH_SITES:
        raise fastapi.HTTPException(status_code=403, detail=FORBIDDEN)
    origin = request.headers.get("origin")
    if origin is not None and (
        origin.rstrip("/") not in services.settings.allowed_origins
    ):
        raise fastapi.HTTPException(status_code=403, detail=FORBIDDEN)


def _unauthorized() -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=401,
        detail=NOT_AUTHENTICATED,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def current_user(
    request: fastapi.Request, services: ServicesDep
) -> tokens.Claims:
    """The caller, from a valid access token of a live session.

    Raises:
        fastapi.HTTPException: 401 without a valid token or session.
    """
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized()
    try:
        claims = tokens.verify(token.strip(), services.settings.jwt_secret)
    except tokens.InvalidTokenError as e:
        raise _unauthorized() from e
    if not await services.sessions.exists(claims.session_id):
        raise _unauthorized()
    return claims


CurrentUser = Annotated[tokens.Claims, fastapi.Depends(current_user)]


def require_role(
    *roles: str,
) -> Callable[[tokens.Claims], Awaitable[tokens.Claims]]:
    """A dependency that only lets the given roles through.

    Args:
        *roles: The allowed roles.

    Returns:
        The dependency; it raises 403 for any other role.
    """
    allowed = frozenset(roles)

    async def dependency(user: CurrentUser) -> tokens.Claims:
        if user.role not in allowed:
            raise fastapi.HTTPException(status_code=403, detail=FORBIDDEN)
        return user

    return dependency
