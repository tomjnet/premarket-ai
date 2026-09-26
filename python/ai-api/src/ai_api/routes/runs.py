"""``/runs``: start a verification run and follow it (ANALYST, ADMIN).

- ``POST /runs`` queues the coordinator job for a feed date (202). One run
  per date at a time (409), and only after the day's rule run and AI run
  are DONE (409 says which is missing).
- ``GET /runs`` / ``GET /runs/{id}``: runs and their counts.
- ``GET /runs/{id}/events``: server-sent events from the run's Redis
  Stream; ``Last-Event-ID`` resumes after a reconnect. The stream ends
  with ``run.done`` or ``run.failed`` (or after an hour).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import datetime
import json
import logging
import time
from typing import Annotated
import zoneinfo

import fastapi
from fastapi import responses

from ai_api import deps
from ai_api import schemas
from ai_api.verify import events as events_lib

_log = logging.getLogger(__name__)
_NEW_YORK = zoneinfo.ZoneInfo("America/New_York")
_OFF = "Verification is not configured"
_NOT_FOUND = "Not found"
_STREAM_MAX_S = 3600
_HEARTBEAT = b": keep-alive\n\n"
# A Redis Stream id: <milliseconds>-<sequence>.
_EVENT_ID = r"^\d{1,20}-\d{1,20}$"

router = fastapi.APIRouter(
    tags=["runs"],
    dependencies=[fastapi.Depends(deps.require_role("ANALYST", "ADMIN"))],
    responses={401: {}, 403: {}},
)


def _require(services: deps.Services) -> None:
    if services.verdicts is None or services.queue is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)


@router.post("/runs", status_code=202, responses={409: {}, 503: {}})
async def start_run(
    body: schemas.RunIn,
    services: deps.ServicesDep,
    user: deps.CurrentUser,
    request: fastapi.Request,
) -> schemas.VerifyRunOut:
    """Queues the verification of one feed date.

    Raises:
        fastapi.HTTPException: 409 when the date isn't ready or already
            has a run in progress; 503 when the queue isn't configured.
    """
    _require(services)
    day = body.date
    if day is None:
        day = datetime.datetime.now(_NEW_YORK).date()
    rule_run = await services.news.latest_rule_run(day)
    ai_run = await services.news.latest_ai_run(day)
    for name, run in (("rule run", rule_run), ("AI run", ai_run)):
        status = None if run is None else run["status"]
        if status != "DONE":
            raise fastapi.HTTPException(
                status_code=409,
                detail=f"The {name} of {day} is {status or 'missing'}",
            )
    if await services.verdicts.active_run(day) is not None:
        raise fastapi.HTTPException(
            status_code=409, detail=f"{day} is already being verified"
        )
    run = await services.verdicts.create_run(day, user.username)
    await services.queue.run_day(run["run_id"])
    await services.users.audit(
        "verify_run",
        user.username,
        deps.client_ip(request),
        {"run_id": run["run_id"], "date": day.isoformat()},
    )
    return schemas.VerifyRunOut.from_row(run)


@router.get("/runs")
async def list_runs(
    services: deps.ServicesDep,
    day: Annotated[datetime.date | None, fastapi.Query(alias="date")] = None,
    limit: Annotated[int, fastapi.Query(ge=1, le=100)] = 20,
) -> schemas.RunListOut:
    """The latest verify runs (of one date, or of any)."""
    _require(services)
    found = await services.verdicts.runs(day, limit)
    items = [schemas.VerifyRunOut.from_row(row) for row in found]
    return schemas.RunListOut(count=len(items), items=items)


@router.get("/runs/{run_id}", responses={404: {}})
async def get_run(
    services: deps.ServicesDep,
    run_id: Annotated[int, fastapi.Path(ge=1, le=2**63 - 1)],
) -> schemas.VerifyRunOut:
    """One verify run and its counts.

    Raises:
        fastapi.HTTPException: 404 when there is no such run.
    """
    _require(services)
    run = await services.verdicts.run(run_id)
    if run is None:
        raise fastapi.HTTPException(status_code=404, detail=_NOT_FOUND)
    return schemas.VerifyRunOut.from_row(run)


def _sse(event_id: str, kind: str, data: dict) -> bytes:
    return (
        f"id: {event_id}\nevent: {kind}\ndata: {json.dumps(data)}\n\n"
    ).encode()


@router.get("/runs/{run_id}/events", responses={404: {}})
async def run_events(
    services: deps.ServicesDep,
    run_id: Annotated[int, fastapi.Path(ge=1, le=2**63 - 1)],
    last_event_id: Annotated[
        str | None,
        fastapi.Header(alias="Last-Event-ID", pattern=_EVENT_ID),
    ] = None,
) -> responses.StreamingResponse:
    """The run's progress as server-sent events (see module docstring).

    Raises:
        fastapi.HTTPException: 404 when there is no such run.
    """
    _require(services)
    if services.run_events is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)
    run = await services.verdicts.run(run_id)
    if run is None:
        raise fastapi.HTTPException(status_code=404, detail=_NOT_FOUND)
    reader = services.run_events

    async def stream() -> AsyncIterator[bytes]:
        after = "0" if last_event_id is None else last_event_id
        started = time.monotonic()
        # A run that ended over a day ago has no stream left: say so.
        if run["status"] in ("DONE", "FAILED"):
            backlog = await reader.read(run_id, after, block_ms=0)
            if not backlog:
                kind = "run.done" if run["status"] == "DONE" else "run.failed"
                yield _sse("0-0", kind, {"status": run["status"]})
                return
        while time.monotonic() - started < _STREAM_MAX_S:
            try:
                found = await reader.read(run_id, after)
            except Exception:  # noqa: BLE001 - end the stream cleanly.
                _log.exception("run events failed")
                return
            if not found:
                yield _HEARTBEAT
                continue
            for event_id, kind, data in found:
                after = event_id
                yield _sse(event_id, kind, data)
                if kind in events_lib.FINAL_KINDS:
                    return

    return responses.StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
