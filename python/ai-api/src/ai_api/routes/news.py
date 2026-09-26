"""``GET /news`` and ``GET /news/{id}``: the feed that replaces the PDF."""

from __future__ import annotations

import datetime
from typing import Annotated, Any
import zoneinfo

import fastapi

from ai_api import deps
from ai_api import news
from ai_api import schemas

_NEW_YORK = zoneinfo.ZoneInfo("America/New_York")
# A US ticker: letters, digits, "." or "-" (BRK.B), at most 10 characters.
_TICKER_PATTERN = r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$"
_NOT_FOUND = "Not found"

router = fastapi.APIRouter(
    tags=["news"],
    dependencies=[
        fastapi.Depends(deps.require_role("TRADER", "ANALYST", "ADMIN"))
    ],
    responses={401: {}, 403: {}},
)


def _item(row: dict[str, Any], *, with_body: bool) -> dict[str, Any]:
    fields = {
        "id": row["id"],
        "vendor_item_id": row["vendor_item_id"],
        "feed_date": row["feed_date"].isoformat(),
        "headline": row["headline"],
        "excerpt": news.excerpt(row["body"]),
        "source_url": row["source_url"],
        "source_domain": row["source_domain"],
        "published_at": schemas.utc_z(row["published_at"]),
        "tickers": list(row["tickers"]),
        "synthetic": row["synthetic"],
        "is_dup": row["is_dup"],
        "dup_of": row["dup_of"],
        "reason_codes": list(row["reason_codes"]),
        "dup_type": row["dup_type"],
        "copies": row["copies"],
        "rules_checked": row["rules_checked"],
    }
    if with_body:
        fields["body"] = row["body"]
        fields["rule_evidence"] = [
            schemas.RuleEvidenceOut(**entry) for entry in row["evidence"] or []
        ]
    return fields


@router.get("/news")
async def list_news(
    services: deps.ServicesDep,
    day: Annotated[datetime.date | None, fastapi.Query(alias="date")] = None,
    ticker: Annotated[
        str | None, fastapi.Query(pattern=_TICKER_PATTERN)
    ] = None,
    q: Annotated[str | None, fastapi.Query(max_length=200)] = None,
    include_duplicates: bool = False,
) -> schemas.NewsListOut:
    """One feed date's news, newest first.

    Args:
        services: Injected services.
        day: The feed date (``date``); defaults to today in New York.
        ticker: Only items tagged with this ticker.
        q: Case-insensitive text in the headline or body.
        include_duplicates: Also return items flagged as duplicates.

    Returns:
        The date's ingest run and rule run (or null) and the matching
        items with their rule results.
    """
    if day is None:
        day = datetime.datetime.now(_NEW_YORK).date()
    text = None if q is None else q.strip()
    query = news.NewsQuery(
        day=day,
        ticker=None if ticker is None else ticker.upper(),
        text=text if text else None,
        include_duplicates=include_duplicates,
    )
    run = await services.news.latest_run(day)
    rule_run = await services.news.latest_rule_run(day)
    rows = await services.news.items(query)
    items = [schemas.NewsItemOut(**_item(row, with_body=False)) for row in rows]
    return schemas.NewsListOut(
        date=day.isoformat(),
        run=None if run is None else schemas.IngestRunOut.from_row(run),
        rule_run=(
            None if rule_run is None else schemas.RuleRunOut.from_row(rule_run)
        ),
        count=len(items),
        items=items,
    )


@router.get("/news/{item_id}", responses={404: {}})
async def get_news_item(
    services: deps.ServicesDep,
    item_id: Annotated[int, fastapi.Path(ge=1, le=2**63 - 1)],
) -> schemas.NewsDetailOut:
    """One item with its full body and the rule evidence.

    Raises:
        fastapi.HTTPException: 404 when there is no such item.
    """
    row = await services.news.item(item_id)
    if row is None:
        raise fastapi.HTTPException(status_code=404, detail=_NOT_FOUND)
    return schemas.NewsDetailOut(**_item(row, with_body=True))
