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
        "summary": row.get("summary"),
        "sentiment": row.get("sentiment"),
        "verdict": row.get("verdict"),
        "confidence": row.get("confidence"),
        "review_status": row.get("review_status"),
        "verdict_source": row.get("verdict_source"),
    }
    if with_body:
        fields["body"] = row["body"]
        fields["rule_evidence"] = [
            schemas.RuleEvidenceOut(**entry) for entry in row["evidence"] or []
        ]
    return fields


def _ai_detail(
    row: dict[str, Any], extraction: list[dict[str, Any]]
) -> schemas.AiDetailOut | None:
    if row.get("ai_status") is None:
        return None
    return schemas.AiDetailOut(
        status=row["ai_status"],
        model=row["ai_model"],
        prompt_version=row["prompt_version"],
        enriched_at=schemas.utc_z(row["enriched_at"]),
        summary_source=row["summary_source"],
        companies=[
            schemas.CompanyOut(name=e["text"], ticker=e["ticker"])
            for e in extraction
            if e["kind"] == "entity"
        ],
        claims=[e["text"] for e in extraction if e["kind"] == "claim"],
        evidence=[
            schemas.AiEvidenceOut(**entry) for entry in row["ai_evidence"] or []
        ],
    )


def _verification(
    found: dict[str, Any],
    evidence: list[dict[str, Any]],
    review: dict[str, Any] | None,
) -> schemas.VerificationOut | None:
    if not found:
        return None
    review_out = None
    if review is not None:
        decided = review["decided_at"]
        review_out = schemas.ReviewOut(
            id=review["id"],
            status=review["status"],
            reasons=list(review["reasons"]),
            ai_verdict=review["ai_verdict"],
            final_verdict=review["final_verdict"],
            reviewer=review["reviewer"],
            comment=review["comment"],
            created_at=schemas.utc_z(review["created_at"]),
            decided_at=None if decided is None else schemas.utc_z(decided),
        )
    return schemas.VerificationOut(
        status=found["status"],
        verdict=found["verdict"],
        confidence=found["confidence"],
        reason_codes=list(found["reason_codes"]),
        rationale=found["rationale"],
        rule_verdict=found["rule_verdict"],
        rule_confidence=found["rule_confidence"],
        judge_verdict=found["judge_verdict"],
        judge_confidence=found["judge_confidence"],
        judge_model=found["judge_model"],
        escalated=found["escalated"],
        review_status=found["review_status"],
        review_reasons=list(found["review_reasons"]),
        impact=found["impact"],
        impact_score=found["impact_score"],
        prompt_version=found["prompt_version"],
        verified_at=schemas.utc_z(found["verified_at"]),
        evidence=[schemas.EvidenceOut(**e) for e in evidence],
        review=review_out,
    )


@router.get("/news")
async def list_news(
    services: deps.ServicesDep,
    day: Annotated[datetime.date | None, fastapi.Query(alias="date")] = None,
    ticker: Annotated[
        str | None, fastapi.Query(pattern=_TICKER_PATTERN)
    ] = None,
    q: Annotated[str | None, fastapi.Query(max_length=200)] = None,
    include_duplicates: bool = False,
    verdict: schemas.Verdict | None = None,
    pending_review: bool = False,
) -> schemas.NewsListOut:
    """One feed date's news, newest first.

    Args:
        services: Injected services.
        day: The feed date (``date``); defaults to today in New York.
        ticker: Only items tagged with this ticker.
        q: Case-insensitive text in the headline or body.
        include_duplicates: Also return items flagged as duplicates.
        verdict: Only items with this verdict.
        pending_review: Only items waiting for an analyst's review.

    Returns:
        The date's ingest, rule, AI and verify runs (or null) and the
        matching items with their rule results, summaries and verdicts.
    """
    if day is None:
        day = datetime.datetime.now(_NEW_YORK).date()
    text = None if q is None else q.strip()
    query = news.NewsQuery(
        day=day,
        ticker=None if ticker is None else ticker.upper(),
        text=text if text else None,
        include_duplicates=include_duplicates,
        verdict=verdict,
        pending_review=pending_review,
    )
    run = await services.news.latest_run(day)
    rule_run = await services.news.latest_rule_run(day)
    ai_run = await services.news.latest_ai_run(day)
    verify_run = await services.news.latest_verify_run(day)
    rows = await services.news.items(query)
    items = [schemas.NewsItemOut(**_item(row, with_body=False)) for row in rows]
    return schemas.NewsListOut(
        date=day.isoformat(),
        run=None if run is None else schemas.IngestRunOut.from_row(run),
        rule_run=(
            None if rule_run is None else schemas.RuleRunOut.from_row(rule_run)
        ),
        ai_run=None if ai_run is None else schemas.AiRunOut.from_row(ai_run),
        verify_run=(
            None
            if verify_run is None
            else schemas.VerifyRunOut.from_row(verify_run)
        ),
        count=len(items),
        items=items,
    )


@router.get("/news/{item_id}", responses={404: {}})
async def get_news_item(
    services: deps.ServicesDep,
    item_id: Annotated[int, fastapi.Path(ge=1, le=2**63 - 1)],
) -> schemas.NewsDetailOut:
    """One item with its body, the rule evidence, AI results and verdict.

    Raises:
        fastapi.HTTPException: 404 when there is no such item.
    """
    row = await services.news.item(item_id)
    if row is None:
        raise fastapi.HTTPException(status_code=404, detail=_NOT_FOUND)
    extraction = await services.news.extraction(item_id)
    found, evidence, review = await services.news.verification(item_id)
    return schemas.NewsDetailOut(
        **_item(row, with_body=True),
        ai=_ai_detail(row, extraction),
        verification=_verification(found, evidence, review),
    )
