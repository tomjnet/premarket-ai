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
Verdict = Literal["VERIFIED", "UNVERIFIED", "MISLEADING", "FAKE"]
ReviewStatus = Literal["PENDING", "APPROVED", "OVERRIDDEN", "EXPIRED"]
VerifyRunStatus = Literal["QUEUED", "RUNNING", "DONE", "FAILED"]
VerificationStatus = Literal["PENDING_REVIEW", "DONE", "FAILED"]
Impact = Literal["low", "medium", "high"]


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


class VerifyRunOut(pydantic.BaseModel):
    """A verification run (``POST /runs``) and its progress."""

    run_id: int
    feed_date: str
    status: VerifyRunStatus
    requested_by: str | None
    requested_at: str
    started_at: str | None
    finished_at: str | None
    total: int
    done: int
    failed: int
    verified: int
    unverified: int
    misleading: int
    fake: int
    pending_review: int
    escalated: int
    model: str | None
    error: str | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> VerifyRunOut:
        """Builds the model from an ``ai.verify_run`` row."""
        times = ("requested_at", "started_at", "finished_at")
        fields = {
            k: row[k]
            for k in cls.model_fields
            if k not in times and k != "feed_date"
        }
        return cls(
            feed_date=row["feed_date"].isoformat(),
            requested_at=utc_z(row["requested_at"]),
            started_at=(
                None if row["started_at"] is None else utc_z(row["started_at"])
            ),
            finished_at=(
                None
                if row["finished_at"] is None
                else utc_z(row["finished_at"])
            ),
            **fields,
        )


class NewsItemOut(pydantic.BaseModel):
    """One item of ``GET /news``.

    ``is_dup`` / ``dup_of`` come from the rule engine once
    ``rules_checked`` is true, else from the legacy exact-hash flags.
    ``reason_codes`` are the rules' codes, then the AI run's, then the
    verification's.
    ``summary`` and ``sentiment`` are null until the AI run
    summarized the item.
    ``verdict`` is null until the item is verified; a duplicate shows its
    original's verdict (``verdict_source: inherited``), and a stale copy
    is MISLEADING. ``review_status`` is PENDING while an analyst hasn't
    decided (the "Pending review" badge).
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
    verdict: Verdict | None
    confidence: float | None
    review_status: ReviewStatus | None
    verdict_source: Literal["ai", "inherited"] | None


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


class EvidenceOut(pydantic.BaseModel):
    """One finding of the verification, numbered like the judge saw it.

    ``check``: entity, source, corroboration, claim, style, stale, dedup,
    guard, language, ml, judge or review. ``url`` / ``title`` link a filing
    or a web result.
    """

    seq: int
    check: str
    code: str | None
    message: str
    source: str
    url: str | None
    title: str | None


class ReviewOut(pydantic.BaseModel):
    """The latest review task of an item."""

    id: int
    status: ReviewStatus
    reasons: list[str]
    ai_verdict: Verdict
    final_verdict: Verdict | None
    reviewer: str | None
    comment: str | None
    created_at: str
    decided_at: str | None


class VerificationOut(pydantic.BaseModel):
    """How the AI reached the verdict (``GET /news/{id}``).

    ``rule_*`` is the deterministic checks' verdict, ``judge_*`` the LLM
    judge's (null when a hard rule decided, or it wasn't asked);
    ``escalated`` means the cloud model judged.
    """

    status: VerificationStatus
    verdict: Verdict | None
    confidence: float | None
    reason_codes: list[str]
    rationale: str
    rule_verdict: Verdict | None
    rule_confidence: float | None
    judge_verdict: Verdict | None
    judge_confidence: float | None
    judge_model: str | None
    escalated: bool
    review_status: ReviewStatus | None
    review_reasons: list[str]
    impact: Impact | None
    impact_score: float | None
    prompt_version: str
    verified_at: str
    evidence: list[EvidenceOut]
    review: ReviewOut | None


class NewsDetailOut(NewsItemOut):
    """``GET /news/{id}``: the item, its body, rule and AI evidence."""

    body: str
    rule_evidence: list[RuleEvidenceOut]
    ai: AiDetailOut | None
    verification: VerificationOut | None


class NewsListOut(pydantic.BaseModel):
    """``GET /news``."""

    date: str
    run: IngestRunOut | None
    rule_run: RuleRunOut | None
    ai_run: AiRunOut | None
    verify_run: VerifyRunOut | None
    count: int
    items: list[NewsItemOut]


class RunIn(pydantic.BaseModel):
    """``POST /runs``: verify one feed date (default today, New York)."""

    model_config = pydantic.ConfigDict(extra="forbid")

    date: datetime.date | None = None


class RunListOut(pydantic.BaseModel):
    """``GET /runs``."""

    count: int
    items: list[VerifyRunOut]


class ReviewTaskOut(pydantic.BaseModel):
    """One task of the review queue.

    ``item_id`` is the news item's id (``GET /news/{id}``).
    """

    id: int
    item_id: int
    vendor_item_id: str
    feed_date: str
    headline: str
    source_domain: str
    tickers: list[str]
    status: ReviewStatus
    reasons: list[str]
    ai_verdict: Verdict
    ai_confidence: float
    final_verdict: Verdict | None
    rule_verdict: Verdict | None
    judge_verdict: Verdict | None
    reason_codes: list[str]
    rationale: str
    impact: Impact | None
    impact_score: float
    reviewer: str | None
    comment: str | None
    created_at: str
    decided_at: str | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ReviewTaskOut:
        """Builds the model from a review queue row."""
        decided = row["decided_at"]
        return cls(
            id=row["id"],
            item_id=row["raw_id"],
            vendor_item_id=row["vendor_item_id"],
            feed_date=row["feed_date"].isoformat(),
            headline=row["headline"],
            source_domain=row["source_domain"],
            tickers=list(row["tickers"]),
            status=row["status"],
            reasons=list(row["reasons"]),
            ai_verdict=row["ai_verdict"],
            ai_confidence=row["ai_confidence"],
            final_verdict=row["final_verdict"],
            rule_verdict=row["rule_verdict"],
            judge_verdict=row["judge_verdict"],
            reason_codes=list(row["reason_codes"] or []),
            rationale=row["rationale"] or "",
            impact=row["impact"],
            impact_score=row["impact_score"],
            reviewer=row["reviewer"],
            comment=row["comment"],
            created_at=utc_z(row["created_at"]),
            decided_at=None if decided is None else utc_z(decided),
        )


class ReviewListOut(pydantic.BaseModel):
    """``GET /review``."""

    count: int
    items: list[ReviewTaskOut]


class ReviewIn(pydantic.BaseModel):
    """``POST /review/{id}``: approve the AI verdict, or override it.

    An override needs the new verdict and a comment (why).
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    action: Literal["approve", "override"]
    verdict: Verdict | None = None
    comment: str = pydantic.Field(default="", max_length=1000)

    @pydantic.model_validator(mode="after")
    def _override_needs_reason(self) -> ReviewIn:
        if self.action == "override":
            if self.verdict is None:
                raise ValueError("an override needs the new verdict")
            if len(self.comment.strip()) < 3:
                raise ValueError("an override needs a comment")
        elif self.verdict is not None:
            raise ValueError("approve takes no verdict")
        return self


class ChatIn(pydantic.BaseModel):
    """``POST /chat``: one question about the news."""

    model_config = pydantic.ConfigDict(extra="forbid")

    question: str = pydantic.Field(min_length=3, max_length=500)
    date: datetime.date | None = None


class HealthOut(pydantic.BaseModel):
    """``GET /health``."""

    status: Literal["ok", "unavailable"]
