"""``/vendor/scorecard``: what the vendor really delivers (ANALYST, ADMIN).

- ``GET /vendor/scorecard?days=30&date=``: the daily rows (newest first)
  with their rates and the averages; the web page draws the 30-day trend.
- ``GET /vendor/scorecard.csv``: the same rows as a CSV download.
- ``GET /vendor/scorecard/summary?days=7``: the weekly summary, written by
  the local model with the ``vendor-scorecard`` skill (cached for an hour
  per last date), or built from the numbers when the model fails.
"""

from __future__ import annotations

import datetime
import json
from typing import Annotated, Any

import fastapi
from fastapi import responses

from ai_api import deps
from ai_api import schemas
from ai_api import scorecard as scorecard_lib

router = fastapi.APIRouter(
    tags=["vendor"],
    dependencies=[fastapi.Depends(deps.require_role("ANALYST", "ADMIN"))],
    responses={401: {}, 403: {}},
)
_OFF = "The vendor scorecard is not configured"
_SUMMARY_TTL_S = 3600

Days = Annotated[int, fastapi.Query(ge=1, le=90)]
Last = Annotated[datetime.date | None, fastapi.Query(alias="date")]


def _store(services: deps.Services) -> scorecard_lib.ScorecardStore:
    if services.scorecard is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)
    return services.scorecard


def _day_out(row: dict[str, Any]) -> schemas.ScorecardDayOut:
    return schemas.ScorecardDayOut(
        **{k: row[k] for k in scorecard_lib.COLUMNS},
        rates=schemas.ScorecardRatesOut(**scorecard_lib.rates(row)),
        computed_at=schemas.utc_z(row["computed_at"]),
    )


@router.get("/vendor/scorecard", responses={503: {}})
async def get_scorecard(
    services: deps.ServicesDep, days: Days = 30, last: Last = None
) -> schemas.ScorecardOut:
    """The daily scorecard rows, newest first."""
    found = await _store(services).days(last, days)
    items = [_day_out(row) for row in found]
    count = len(found) or 1
    return schemas.ScorecardOut(
        count=len(items),
        items=items,
        average_billable=round(sum(r["billable"] for r in found) / count, 1),
        contracted=found[0]["contracted"]
        if found
        else scorecard_lib.DEFAULT_CONTRACTED,
    )


@router.get(
    "/vendor/scorecard.csv",
    response_class=responses.PlainTextResponse,
    responses={503: {}},
)
async def scorecard_csv(
    services: deps.ServicesDep, days: Days = 30, last: Last = None
) -> responses.PlainTextResponse:
    """The rows as a CSV download (oldest first)."""
    found = await _store(services).days(last, days)
    return responses.PlainTextResponse(
        scorecard_lib.to_csv(found),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="vendor-scorecard.csv"'
        },
    )


@router.get("/vendor/scorecard/summary", responses={503: {}})
async def scorecard_summary(
    services: deps.ServicesDep, days: Days = 7, last: Last = None
) -> schemas.ScorecardSummaryOut:
    """The weekly summary (see the module docstring)."""
    found = await _store(services).days(last, days)
    if not found:
        return schemas.ScorecardSummaryOut(
            text=scorecard_lib.fallback_summary(found),
            source="fallback",
            model="",
            days=0,
            last_date=None,
        )
    newest = found[0]["feed_date"]
    key = f"scorecard:summary:{newest.isoformat()}:{len(found)}"
    cached = None if services.cache is None else await services.cache.get(key)
    if cached is not None:
        return schemas.ScorecardSummaryOut.model_validate_json(cached)
    if services.summarizer is None:
        summary = scorecard_lib.Summary(
            scorecard_lib.fallback_summary(found), "fallback", ""
        )
    else:
        summary = await services.summarizer.write(found)
    out = schemas.ScorecardSummaryOut(
        text=summary.text,
        source=summary.source,
        model=summary.model,
        days=len(found),
        last_date=newest,
    )
    if services.cache is not None:
        await services.cache.set(
            key, json.dumps(out.model_dump(mode="json")), ex=_SUMMARY_TTL_S
        )
    return out
