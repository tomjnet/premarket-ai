"""``POST /chat``: "Ask the News", streamed as server-sent events.

Events: ``sources`` (the numbered sources), ``token`` (answer text as the
model writes it), then ``done`` (the checked answer, its citations and
metadata) or ``error``. The browser shows the tokens as they arrive and
replaces them with the ``done`` text, which has invalid citations removed
and never contains investment advice.

One question per user at a time: the GPU runs one model, and a second
tab's question would only queue behind the first.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import datetime
import json
import logging
import zoneinfo

import fastapi
from fastapi import responses
from redis import asyncio as aioredis

from ai_api import deps
from ai_api import schemas

_log = logging.getLogger(__name__)
_NEW_YORK = zoneinfo.ZoneInfo("America/New_York")
_LOCK_S = 180
_BUSY = "Another question of yours is still being answered"
_OFF = "Ask the News is not configured"

router = fastapi.APIRouter(
    tags=["chat"],
    dependencies=[
        fastapi.Depends(deps.require_role("TRADER", "ANALYST", "ADMIN"))
    ],
    responses={401: {}, 403: {}},
)


class ChatGate:
    """One question in flight per user (a Redis lock with a timeout)."""

    def __init__(self, redis: aioredis.Redis, ttl_s: int = _LOCK_S) -> None:
        """Uses ``redis``; a crashed answer frees the lock after ``ttl_s``."""
        self._redis = redis
        self._ttl_s = ttl_s

    async def enter(self, user: str) -> bool:
        """True when the user had no question in flight."""
        return bool(
            await self._redis.set(
                f"chat:busy:{user}", "1", nx=True, ex=self._ttl_s
            )
        )

    async def leave(self, user: str) -> None:
        """Frees the user's slot."""
        await self._redis.delete(f"chat:busy:{user}")


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


@router.post("/chat", responses={429: {}, 503: {}})
async def chat(
    body: schemas.ChatIn,
    services: deps.ServicesDep,
    user: deps.CurrentUser,
    request: fastapi.Request,
) -> responses.StreamingResponse:
    """Answers a question from the trusted corpus and the day's news.

    Args:
        body: The question and the feed date (default today, New York).
        services: Injected services.
        user: The caller.
        request: The request (audit IP).

    Returns:
        A ``text/event-stream`` of ``sources``, ``token`` and ``done``.

    Raises:
        fastapi.HTTPException: 503 when chat isn't configured, 429 when
            the user already has a question in flight.
    """
    if services.ask is None or services.chat_gate is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)
    if not await services.chat_gate.enter(user.username):
        raise fastapi.HTTPException(status_code=429, detail=_BUSY)
    day = body.date
    if day is None:
        day = datetime.datetime.now(_NEW_YORK).date()
    await services.users.audit(
        "chat",
        user.username,
        deps.client_ip(request),
        {"chars": len(body.question), "date": day.isoformat()},
    )

    async def events() -> AsyncIterator[bytes]:
        try:
            async for event in services.ask.stream(
                body.question, day, user.username
            ):
                yield _sse(event.name, event.data)
        except Exception:  # noqa: BLE001 - the stream must end cleanly.
            _log.exception("chat failed")
            yield _sse(
                "error",
                {"detail": "The answer failed. Try again in a moment."},
            )
        finally:
            await services.chat_gate.leave(user.username)

    return responses.StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
