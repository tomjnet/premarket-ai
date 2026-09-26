"""``/briefs``: the pre-market brief (Today's Brief page).

- ``GET /briefs/today?date=`` (every role): the date's current brief as
  server-sent events. ``brief`` (which brief, its state) comes first; a
  finished brief then comes at once as ``done``. A brief still being
  written streams its progress from ``brief:{id}:events`` (``status``,
  ``sections``) and ends with ``done`` (the whole brief) or ``error``.
  The ``done`` brief is personal: it lists the caller's watchlist items.
  ``404`` when the date has no brief yet. Every view is audited (action
  ``brief``), which shows whether traders read the brief instead of the
  PDF.
- ``POST /briefs`` (ANALYST, ADMIN): write the brief of a date now
  (``edition`` ``morning`` or ``refresh``); ``409`` until the date's
  verification is DONE, or while a brief of the date is being written.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import datetime
import json
import logging
import time
from typing import Annotated, Any
import zoneinfo

import fastapi
from fastapi import responses

from ai_api import briefs as briefs_lib
from ai_api import deps
from ai_api import memory as memory_lib
from ai_api import schemas

_log = logging.getLogger(__name__)
_NEW_YORK = zoneinfo.ZoneInfo("America/New_York")
_OFF = "The brief is not configured"
_STREAM_MAX_S = 900
_HEARTBEAT = b": keep-alive\n\n"
_FAILED = "The brief failed. An analyst can write it again."
_SLOW = "The brief is still being written. Reload the page in a minute."
_FINAL = frozenset({"brief.done", "brief.failed"})

router = fastapi.APIRouter(tags=["briefs"], responses={401: {}, 403: {}})
_ANY_ROLE = fastapi.Depends(deps.require_role("TRADER", "ANALYST", "ADMIN"))
_REVIEWERS = fastapi.Depends(deps.require_role("ANALYST", "ADMIN"))


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


def _today() -> datetime.date:
    return datetime.datetime.now(_NEW_YORK).date()


async def _watchlist(
    services: deps.Services, user: str
) -> memory_lib.Watchlist:
    if services.memory is None:
        return memory_lib.Watchlist()
    try:
        return await services.memory.watchlist(user)
    except Exception as e:  # noqa: BLE001 - the brief without it.
        _log.warning("watchlist unavailable: %r", e)
        return memory_lib.Watchlist()


def _done(
    row: dict[str, Any], watchlist: memory_lib.Watchlist
) -> dict[str, Any]:
    mine = schemas.BriefWatchlistOut(
        tickers=list(watchlist.tickers),
        sectors=list(watchlist.sectors),
        items=briefs_lib.for_user(row["content"] or {}, watchlist),
    )
    return schemas.BriefOut.from_brief(row, mine).model_dump()


@router.get("/briefs/today", dependencies=[_ANY_ROLE], responses={404: {}})
async def today(
    services: deps.ServicesDep,
    user: deps.CurrentUser,
    request: fastapi.Request,
    day: Annotated[datetime.date | None, fastapi.Query(alias="date")] = None,
) -> responses.StreamingResponse:
    """The date's brief as server-sent events (see the module docstring).

    Raises:
        fastapi.HTTPException: 404 when the date has no brief, 503 when
            briefs aren't configured.
    """
    if services.briefs is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)
    if day is None:
        day = _today()
    row = await services.briefs.current(day)
    if row is None:
        raise fastapi.HTTPException(
            status_code=404, detail=f"No brief for {day} yet"
        )
    await services.users.audit(
        "brief",
        user.username,
        deps.client_ip(request),
        {"date": day.isoformat(), "brief_id": row["brief_id"]},
    )
    watchlist = await _watchlist(services, user.username)
    store = services.briefs
    reader = services.brief_events

    async def stream() -> AsyncIterator[bytes]:
        yield _sse("brief", schemas.BriefMetaOut.from_row(row).model_dump())
        if row["status"] == "DONE":
            yield _sse("done", _done(row, watchlist))
            return
        if row["status"] == "FAILED" or reader is None:
            yield _sse("error", {"detail": _FAILED})
            return
        after = "0"
        started = time.monotonic()
        while time.monotonic() - started < _STREAM_MAX_S:
            try:
                found = await reader.read(row["brief_id"], after)
            except Exception:  # noqa: BLE001 - end the stream cleanly.
                _log.exception("brief events failed")
                break
            if not found:
                yield _HEARTBEAT
                continue
            for event_id, kind, data in found:
                after = event_id
                if kind not in _FINAL:
                    yield _sse(kind, data)
                    continue
                final = await store.get(row["brief_id"])
                if kind == "brief.done" and final is not None:
                    yield _sse("done", _done(final, watchlist))
                else:
                    yield _sse("error", {"detail": _FAILED})
                return
        yield _sse("error", {"detail": _SLOW})

    return responses.StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@router.post(
    "/briefs",
    status_code=202,
    dependencies=[_REVIEWERS],
    responses={409: {}, 503: {}},
)
async def write_brief(
    body: schemas.BriefIn,
    services: deps.ServicesDep,
    user: deps.CurrentUser,
    request: fastapi.Request,
) -> schemas.BriefMetaOut:
    """Queues the brief of a date.

    Raises:
        fastapi.HTTPException: 409 when the date's verification isn't DONE
            or a brief is being written; 503 when briefs aren't configured.
    """
    if services.briefs is None or services.queue is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)
    day = body.date if body.date is not None else _today()
    run = await services.news.latest_verify_run(day)
    status = None if run is None else run["status"]
    if status != "DONE":
        raise fastapi.HTTPException(
            status_code=409,
            detail=f"The AI verification of {day} is {status or 'missing'}",
        )
    if await services.briefs.active(day) is not None:
        raise fastapi.HTTPException(
            status_code=409, detail=f"The brief of {day} is being written"
        )
    brief = await services.briefs.create(day, body.edition, user.username)
    await services.queue.write_brief(brief["brief_id"])
    await services.users.audit(
        "brief_write",
        user.username,
        deps.client_ip(request),
        {
            "brief_id": brief["brief_id"],
            "date": day.isoformat(),
            "edition": body.edition,
        },
    )
    return schemas.BriefMetaOut.from_row(brief)
