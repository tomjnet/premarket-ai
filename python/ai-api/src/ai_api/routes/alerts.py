"""``/alerts``: the operations banner, and the cloud budget.

- ``POST /alerts/grafana``: Grafana's webhook contact point (increment 6).
  It needs ``Authorization: Bearer <ALERT_WEBHOOK_TOKEN>`` and is not
  reachable through the edge (only Grafana, on the container network,
  calls it). Each alert of the payload goes to the Redis Stream ``alerts``.
- ``GET /alerts``: the alerts firing now (ANALYST, ADMIN).
- ``GET /alerts/stream``: server-sent events (ANALYST, ADMIN): a
  ``snapshot`` of the firing alerts, then every new ``alert`` event
  (``firing`` or ``resolved``). ``Last-Event-ID`` resumes after a
  reconnect. The stream ends after an hour; the browser reconnects.
- ``GET /llm/budget``: this month's cloud spend against the cap (every
  role: the "Cloud budget reached, running local" banner).
- ``GET /schedule?date=``: the scheduler's jobs and SLA checks of a day
  (ANALYST, ADMIN).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import datetime
import hmac
import json
import logging
import time
from typing import Annotated, Any
import zoneinfo

import fastapi
from fastapi import responses
import pydantic

from ai_api import alerts as alerts_lib
from ai_api import deps
from ai_api import schemas

_log = logging.getLogger(__name__)
_STREAM_MAX_S = 3600
_HEARTBEAT = b": keep-alive\n\n"
_EVENT_ID = r"^\d{1,20}-\d{1,20}$"
_OFF = "Alerts are not configured"
# Grafana re-sends a firing alert every repeat interval (4 h); the banner
# needs it once.
_GRAFANA_DEDUP_S = 3600
_MAX_ALERTS = 50
_NEW_YORK = zoneinfo.ZoneInfo("America/New_York")

router = fastapi.APIRouter(tags=["alerts"])
_ops = [fastapi.Depends(deps.require_role("ANALYST", "ADMIN"))]


class _GrafanaAlert(pydantic.BaseModel):
    """One alert of Grafana's webhook payload (the fields used)."""

    model_config = pydantic.ConfigDict(extra="ignore")

    status: str = "firing"
    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}
    fingerprint: str = ""


class _GrafanaPayload(pydantic.BaseModel):
    """Grafana's webhook payload (alerting v11+)."""

    model_config = pydantic.ConfigDict(extra="ignore")

    alerts: list[_GrafanaAlert] = pydantic.Field(
        default_factory=list, max_length=_MAX_ALERTS
    )


def _to_alert(found: _GrafanaAlert) -> alerts_lib.Alert:
    name = found.labels.get("alertname", "grafana")[:80]
    severity = found.labels.get("severity", "warning")
    if severity not in alerts_lib.SEVERITIES:
        severity = "warning"
    status = "resolved" if found.status == "resolved" else "firing"
    title = (found.annotations.get("summary") or name)[:200]
    return alerts_lib.Alert(
        key=f"grafana:{name}:{found.fingerprint[:40] or 'all'}",
        title=title,
        severity=severity,
        status=status,
        detail=found.annotations.get("description", "")[:1000],
        source="grafana",
    )


def _webhook_token(request: fastapi.Request, services: deps.Services) -> None:
    expected = services.settings.alert_webhook_token
    if not expected:
        # Not configured: the endpoint doesn't exist.
        raise fastapi.HTTPException(status_code=404, detail="Not found")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        token.strip().encode(), expected.encode()
    ):
        raise fastapi.HTTPException(
            status_code=401,
            detail=deps.NOT_AUTHENTICATED,
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post(
    "/alerts/grafana",
    status_code=204,
    responses={401: {}, 404: {}, 503: {}},
    include_in_schema=False,
)
async def grafana_webhook(
    payload: _GrafanaPayload,
    request: fastapi.Request,
    services: deps.ServicesDep,
) -> fastapi.Response:
    """Publishes Grafana's alerts to the banner stream.

    Raises:
        fastapi.HTTPException: 404 when no token is configured, 401 for a
            wrong token, 503 without Redis alerts.
    """
    _webhook_token(request, services)
    if services.alerts is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)
    published = 0
    for found in payload.alerts:
        event = await services.alerts.publish(
            _to_alert(found), dedup_s=_GRAFANA_DEDUP_S
        )
        published += event is not None
    _log.info(
        "grafana webhook: %d alerts, %d published",
        len(payload.alerts),
        published,
    )
    return fastapi.Response(status_code=204)


def _require(services: deps.Services) -> alerts_lib.Alerts:
    if services.alerts is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)
    return services.alerts


def _out(alert: dict[str, Any]) -> schemas.AlertOut:
    return schemas.AlertOut.model_validate(alert)


@router.get("/alerts", dependencies=_ops, responses={401: {}, 403: {}})
async def list_alerts(services: deps.ServicesDep) -> schemas.AlertListOut:
    """The alerts firing now (the last day's events)."""
    reader = _require(services)
    active = alerts_lib.active(await reader.since())
    items = [_out(a) for a in active]
    return schemas.AlertListOut(count=len(items), items=items)


def _sse(event_id: str, kind: str, data: Any) -> bytes:
    return (
        f"id: {event_id}\nevent: {kind}\ndata: {json.dumps(data)}\n\n"
    ).encode()


@router.get("/alerts/stream", dependencies=_ops, responses={401: {}, 403: {}})
async def alert_stream(
    services: deps.ServicesDep,
    last_event_id: Annotated[
        str | None,
        fastapi.Header(alias="Last-Event-ID", pattern=_EVENT_ID),
    ] = None,
) -> responses.StreamingResponse:
    """The banner's server-sent events (see the module docstring)."""
    reader = _require(services)

    async def stream() -> AsyncIterator[bytes]:
        started = time.monotonic()
        recent = await reader.since()
        after = recent[-1][0] if recent else "0-0"
        if last_event_id is not None:
            after = last_event_id
        snapshot = [
            _out(a).model_dump(mode="json") for a in alerts_lib.active(recent)
        ]
        yield _sse(after, "snapshot", {"items": snapshot})
        while time.monotonic() - started < _STREAM_MAX_S:
            try:
                found = await reader.read(after)
            except Exception:  # noqa: BLE001 - end the stream cleanly.
                _log.exception("alert stream failed")
                return
            if not found:
                yield _HEARTBEAT
                continue
            for event_id, data in found:
                after = event_id
                alert = _out(dict(data, id=event_id)).model_dump(mode="json")
                yield _sse(event_id, "alert", alert)

    return responses.StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@router.get("/schedule", dependencies=_ops, responses={401: {}, 403: {}})
async def day_schedule(
    services: deps.ServicesDep,
    day: Annotated[datetime.date | None, fastapi.Query(alias="date")] = None,
) -> schemas.ScheduleOut:
    """The scheduler's jobs and SLA checks of a day (default: today, ET)."""
    if services.schedule is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)
    if day is None:
        day = datetime.datetime.now(_NEW_YORK).date()
    found = await services.schedule.runs(day)
    items = [
        schemas.ScheduleRunOut(
            job=row["job"],
            run_mode=row["run_mode"],
            status=row["status"],
            started_at=schemas.utc_z(row["started_at"]),
            finished_at=None
            if row["finished_at"] is None
            else schemas.utc_z(row["finished_at"]),
            detail=row["detail"],
        )
        for row in found
    ]
    sla = [i for i in items if i.job.startswith("sla-")]
    return schemas.ScheduleOut(
        date=day,
        items=items,
        sla_checked=len(sla),
        sla_green=bool(sla) and all(i.status == "OK" for i in sla),
    )


@router.get("/llm/budget", responses={401: {}})
async def cloud_budget(
    services: deps.ServicesDep, user: deps.CurrentUser
) -> schemas.BudgetOut:
    """This month's cloud spend and cap (the budget banner)."""
    del user
    if services.budget is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)
    spent = await services.budget.spent()
    cap = services.budget.cap_usd
    share = spent / cap if cap > 0 else 1.0
    return schemas.BudgetOut(
        spent_usd=round(spent, 4),
        cap_usd=cap,
        share=round(min(share, 9.99), 4),
        warning=share >= 0.8,
        reached=share >= 1.0,
    )
