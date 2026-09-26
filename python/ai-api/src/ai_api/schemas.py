"""Response models: the wire contract with the web UI (snake_case JSON).

The UI parses every response with its zod schemas (``ui/web/src/api/
schemas``); these models are the backend side of the same contract, and
``ai-api openapi`` prints them for comparison.
"""

from __future__ import annotations

import datetime
from typing import Any, Literal

import pydantic

Role = Literal["TRADER", "ANALYST", "ADMIN"]
RunStatus = Literal["RUNNING", "DONE", "FAILED"]
DupType = Literal["url", "exact", "near", "paraphrase"]
RuleCheck = Literal["entity", "source", "dedup", "stale"]


def utc_z(value: datetime.datetime) -> str:
    """Formats a timestamp as ISO 8601 UTC with a ``Z``, whole seconds."""
    return (
        value.astimezone(datetime.UTC)
        .replace(microsecond=0, tzinfo=None)
        .isoformat()
        + "Z"
    )


class UserOut(pydantic.BaseModel):
    """The logged-in user."""

    username: str
    role: Role


class TokenOut(pydantic.BaseModel):
    """``POST /auth/login`` and ``POST /auth/refresh``."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut


class IngestRunOut(pydantic.BaseModel):
    """The ingest run of a feed date."""

    run_id: int
    status: RunStatus
    started_at: str
    finished_at: str | None
    rows_received: int
    dups: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> IngestRunOut:
        """Builds the model from a ``legacy.ingest_run`` row."""
        finished = row["finished_at"]
        return cls(
            run_id=row["run_id"],
            status=row["status"],
            started_at=utc_z(row["started_at"]),
            finished_at=None if finished is None else utc_z(finished),
            rows_received=row["rows_received"],
            dups=row["dups"],
        )


class RuleRunOut(pydantic.BaseModel):
    """The latest rule-check run of a feed date."""

    status: RunStatus
    finished_at: str | None
    items: int
    duplicates: int
    flagged: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RuleRunOut:
        """Builds the model from an ``ai.rule_run`` row."""
        finished = row["finished_at"]
        return cls(
            status=row["status"],
            finished_at=None if finished is None else utc_z(finished),
            items=row["items"],
            duplicates=row["duplicates"],
            flagged=row["flagged"],
        )


class NewsItemOut(pydantic.BaseModel):
    """One item of ``GET /news``.

    ``is_dup`` / ``dup_of`` come from the rule engine once
    ``rules_checked`` is true, else from the legacy exact-hash flags.
    """

    id: int
    vendor_item_id: str
    feed_date: str
    headline: str
    excerpt: str
    source_url: str
    source_domain: str
    published_at: str
    tickers: list[str]
    synthetic: bool
    is_dup: bool
    dup_of: str | None
    reason_codes: list[str]
    dup_type: DupType | None
    copies: int
    rules_checked: bool


class RuleEvidenceOut(pydantic.BaseModel):
    """Why a rule flagged (or cleared) an item; plain text."""

    check: RuleCheck
    code: str | None
    message: str


class NewsDetailOut(NewsItemOut):
    """``GET /news/{id}``: the item, its full body and rule evidence."""

    body: str
    rule_evidence: list[RuleEvidenceOut]


class NewsListOut(pydantic.BaseModel):
    """``GET /news``."""

    date: str
    run: IngestRunOut | None
    rule_run: RuleRunOut | None
    count: int
    items: list[NewsItemOut]


class HealthOut(pydantic.BaseModel):
    """``GET /health``."""

    status: Literal["ok", "unavailable"]
