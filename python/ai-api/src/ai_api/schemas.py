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
AiCheck = Literal["guard", "language", "dedup"]
AiStatus = Literal["DONE", "SKIPPED", "DUPLICATE", "FAILED"]
Sentiment = Literal["bullish", "neutral", "bearish"]


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


class AiRunOut(pydantic.BaseModel):
    """The latest AI run (summaries, L3) of a feed date."""

    status: RunStatus
    finished_at: str | None
    items: int
    paraphrases: int
    conflicts: int
    summarized: int
    fallbacks: int
    failed: int
    model: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> AiRunOut:
        """Builds the model from an ``ai.ai_run`` row."""
        finished = row["finished_at"]
        fields = {k: row[k] for k in cls.model_fields if k != "finished_at"}
        return cls(
            finished_at=None if finished is None else utc_z(finished),
            **fields,
        )


class NewsItemOut(pydantic.BaseModel):
    """One item of ``GET /news``.

    ``is_dup`` / ``dup_of`` come from the rule engine once
    ``rules_checked`` is true, else from the legacy exact-hash flags.
    ``reason_codes`` are the rules' codes, then the AI run's.
    ``summary`` and ``sentiment`` are null until the AI run
    summarized the item.
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
    summary: str | None
    sentiment: Sentiment | None


class RuleEvidenceOut(pydantic.BaseModel):
    """Why a rule flagged (or cleared) an item; plain text."""

    check: RuleCheck
    code: str | None
    message: str


class AiEvidenceOut(pydantic.BaseModel):
    """Why the AI run flagged an item; plain text."""

    check: AiCheck
    code: str | None
    message: str


class CompanyOut(pydantic.BaseModel):
    """A company the item names (extracted by the model)."""

    name: str
    ticker: str | None


class AiDetailOut(pydantic.BaseModel):
    """What the AI run did with an item.

    ``summary_source`` is ``fallback`` when the model couldn't write a
    clean summary and the story's lead sentence is shown instead.
    """

    status: AiStatus
    model: str
    prompt_version: str
    enriched_at: str
    summary_source: Literal["llm", "fallback"] | None
    companies: list[CompanyOut]
    claims: list[str]
    evidence: list[AiEvidenceOut]


class NewsDetailOut(NewsItemOut):
    """``GET /news/{id}``: the item, its body, rule and AI evidence."""

    body: str
    rule_evidence: list[RuleEvidenceOut]
    ai: AiDetailOut | None


class NewsListOut(pydantic.BaseModel):
    """``GET /news``."""

    date: str
    run: IngestRunOut | None
    rule_run: RuleRunOut | None
    ai_run: AiRunOut | None
    count: int
    items: list[NewsItemOut]


class ChatIn(pydantic.BaseModel):
    """``POST /chat``: one question about the news."""

    model_config = pydantic.ConfigDict(extra="forbid")

    question: str = pydantic.Field(min_length=3, max_length=500)
    date: datetime.date | None = None


class HealthOut(pydantic.BaseModel):
    """``GET /health``."""

    status: Literal["ok", "unavailable"]
