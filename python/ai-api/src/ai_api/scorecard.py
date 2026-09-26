"""The vendor scorecard (increment 6): what the vendor really delivers.

``compute`` (``ai-api scorecard --date D``, as the owner) counts one feed
date from the AI side's results and stores a snapshot row in
``ai.vendor_scorecard``; the scheduler runs it at 09:35 ET, after the
pending reviews expired. The API reads the rows (``GET /vendor/scorecard``,
CSV export), and ``Summarizer`` writes the weekly summary with the local
model and the ``vendor-scorecard`` skill.

Definitions (the skill's): unique items are what's left after the four
duplicate levels; **billable = unique items that are VERIFIED or
UNVERIFIED** (UNVERIFIED may be real breaking news); FAKE, MISLEADING and
duplicates don't count. The contract is ``VENDOR_CONTRACT_ITEMS`` (100) a
day.
"""

from __future__ import annotations

from collections.abc import Sequence
import csv
import dataclasses
import datetime
import io
import json
import logging
from typing import Any, Protocol

import psycopg
from psycopg import rows
from psycopg_pool import AsyncConnectionPool

_log = logging.getLogger(__name__)
DEFAULT_CONTRACTED = 100
PROMPT_VERSION = "scorecard-v1"

COLUMNS = (
    "feed_date",
    "received",
    "unique_items",
    "duplicates",
    "dup_url",
    "dup_exact",
    "dup_near",
    "dup_paraphrase",
    "stale",
    "verified",
    "unverified",
    "misleading",
    "fake",
    "failed",
    "pending_review",
    "injection",
    "avg_corroboration",
    "reviewed",
    "overridden",
    "billable",
    "contracted",
    "cloud_cost_usd",
)

_COUNTS_SQL = """
WITH n AS (
  SELECT n.id,
         d.news_id IS NOT NULL AS dup,
         d.dup_type,
         coalesce(d.stale, false) AS stale_copy,
         coalesce(r.reason_codes, '{}') || coalesce(a.reason_codes, '{}')
           AS codes,
         v.verdict::text AS verdict,
         v.status AS verify_status,
         v.review_status
  FROM ai.news_item n
  LEFT JOIN ai.duplicate_link d ON d.news_id = n.id
  LEFT JOIN ai.rule_check r ON r.news_id = n.id
  LEFT JOIN ai.news_ai a ON a.news_id = n.id
  LEFT JOIN ai.verification v ON v.news_id = n.id
  WHERE n.feed_date = %(day)s
)
SELECT count(*) AS received,
       count(*) FILTER (WHERE NOT dup) AS unique_items,
       count(*) FILTER (WHERE dup) AS duplicates,
       count(*) FILTER (WHERE dup_type = 'url') AS dup_url,
       count(*) FILTER (WHERE dup_type = 'exact') AS dup_exact,
       count(*) FILTER (WHERE dup_type = 'near') AS dup_near,
       count(*) FILTER (WHERE dup_type = 'paraphrase') AS dup_paraphrase,
       count(*) FILTER (WHERE stale_copy OR 'STALE' = ANY (codes)) AS stale,
       count(*) FILTER (WHERE NOT dup AND verdict = 'VERIFIED') AS verified,
       count(*) FILTER (WHERE NOT dup AND verdict = 'UNVERIFIED')
         AS unverified,
       count(*) FILTER (WHERE NOT dup AND verdict = 'MISLEADING')
         AS misleading,
       count(*) FILTER (WHERE NOT dup AND verdict = 'FAKE') AS fake,
       count(*) FILTER (WHERE NOT dup AND verify_status = 'FAILED') AS failed,
       count(*) FILTER (WHERE NOT dup AND review_status = 'PENDING')
         AS pending_review,
       count(*) FILTER (WHERE 'INJECTION_ATTEMPT' = ANY (codes)) AS injection
FROM n
"""

_CORROBORATION_SQL = """
SELECT coalesce(avg(linked), 0) AS avg_corroboration
FROM (
  SELECT v.news_id,
         count(e.seq) FILTER (WHERE e.check_type = 'corroboration'
                              AND e.url IS NOT NULL) AS linked
  FROM ai.verification v
  JOIN ai.news_item n ON n.id = v.news_id
  LEFT JOIN ai.evidence e ON e.news_id = v.news_id
  WHERE n.feed_date = %(day)s AND v.status <> 'FAILED'
  GROUP BY v.news_id
) per_item
"""

_REVIEWS_SQL = """
SELECT count(*) FILTER (WHERE t.status IN ('APPROVED', 'OVERRIDDEN'))
         AS reviewed,
       count(*) FILTER (WHERE t.status = 'OVERRIDDEN') AS overridden
FROM ai.review_task t JOIN ai.news_item n ON n.id = t.news_id
WHERE n.feed_date = %(day)s
"""

_UPSERT_SQL = f"""
INSERT INTO ai.vendor_scorecard ({", ".join(COLUMNS)}, computed_at)
VALUES ({", ".join(f"%({c})s" for c in COLUMNS)}, now())
ON CONFLICT (feed_date) DO UPDATE SET
{", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS[1:])},
computed_at = now()
"""


def compute(
    conn: psycopg.Connection[Any],
    day: datetime.date,
    contracted: int = DEFAULT_CONTRACTED,
    cloud_cost_usd: float = 0.0,
) -> dict[str, Any]:
    """Counts ``day`` and stores its scorecard row (owner, one transaction).

    Args:
        conn: An owner connection.
        day: The feed date.
        contracted: Items per day in the contract.
        cloud_cost_usd: The cloud spend of that day.

    Returns:
        The row as stored.
    """
    params = {"day": day}
    cur = conn.cursor(row_factory=rows.dict_row)
    with conn.transaction():
        counts = cur.execute(_COUNTS_SQL, params).fetchone()
        counts.update(cur.execute(_CORROBORATION_SQL, params).fetchone())
        counts.update(cur.execute(_REVIEWS_SQL, params).fetchone())
        row = {
            **{k: int(v) for k, v in counts.items()},
            "feed_date": day,
            "avg_corroboration": round(float(counts["avg_corroboration"]), 3),
            "billable": int(counts["verified"]) + int(counts["unverified"]),
            "contracted": contracted,
            "cloud_cost_usd": round(cloud_cost_usd, 4),
        }
        cur.execute(_UPSERT_SQL, row)
    return row


def rates(row: dict[str, Any]) -> dict[str, float]:
    """The shares the UI and the summary show (0 to 1).

    Duplicate and stale rates are of the items received; FAKE, MISLEADING
    and the billable share of the unique items; the override rate of the
    decided reviews.
    """

    def share(part: float, whole: float) -> float:
        return round(part / whole, 4) if whole else 0.0

    received = row["received"]
    unique = row["unique_items"]
    return {
        "duplicate_rate": share(row["duplicates"], received),
        "stale_rate": share(row["stale"], received),
        "fake_rate": share(row["fake"], unique),
        "misleading_rate": share(row["misleading"], unique),
        "override_rate": share(row["overridden"], row["reviewed"]),
        "billable_vs_contract": share(row["billable"], row["contracted"]),
    }


def to_csv(found: Sequence[dict[str, Any]]) -> str:
    """The rows as CSV (oldest first), with the rates."""
    out = io.StringIO()
    names = [*COLUMNS, *rates(dict.fromkeys(COLUMNS, 0))]
    writer = csv.DictWriter(out, fieldnames=names, lineterminator="\n")
    writer.writeheader()
    for row in sorted(found, key=lambda r: r["feed_date"]):
        writer.writerow(
            {
                **{k: row[k] for k in COLUMNS},
                "feed_date": row["feed_date"].isoformat(),
                **rates(row),
            }
        )
    return out.getvalue()


class ScorecardStore(Protocol):
    """Reads the scorecard (the API's role)."""

    async def days(
        self, last: datetime.date | None, count: int
    ) -> list[dict[str, Any]]:
        """The ``count`` newest rows up to ``last`` (newest first)."""


class PostgresScorecard:
    """``ScorecardStore`` over the API's pool."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Uses ``pool``."""
        self._pool = pool

    async def days(
        self, last: datetime.date | None, count: int
    ) -> list[dict[str, Any]]:
        """The ``count`` newest rows up to ``last`` (newest first)."""
        async with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(
                f"SELECT {', '.join(COLUMNS)}, computed_at"
                " FROM ai.vendor_scorecard"
                " WHERE %(last)s::date IS NULL OR feed_date <= %(last)s"
                " ORDER BY feed_date DESC LIMIT %(count)s",
                {"last": last, "count": count},
            )
            return await cur.fetchall()


@dataclasses.dataclass(frozen=True)
class Summary:
    """The weekly summary.

    Attributes:
        text: At most about 150 words (the skill's format).
        source: ``llm``, or ``fallback`` (a sentence built from the numbers
            when the model failed the checks).
        model: The model that wrote it.
    """

    text: str
    source: str
    model: str


def fallback_summary(found: Sequence[dict[str, Any]]) -> str:
    """A factual summary built from the numbers (no model)."""
    if not found:
        return "No scorecard days yet."
    days = len(found)
    billable = sum(r["billable"] for r in found) / days
    contracted = found[0]["contracted"]
    received = sum(r["received"] for r in found)
    duplicates = sum(r["duplicates"] for r in found)
    fake = sum(r["fake"] for r in found)
    unique = sum(r["unique_items"] for r in found) or 1
    return (
        f"Over {days} days the vendor delivered {billable:.0f} billable items"
        f" per day against {contracted} contracted."
        f" {duplicates / max(received, 1):.0%} of the items received were"
        f" duplicates and {fake / unique:.0%} of the unique items were FAKE."
    )


class Summarizer:
    """Writes the weekly vendor summary with the ``vendor-scorecard`` skill."""

    def __init__(self, model: Any, model_name: str, skill: str) -> None:
        """Uses a chat model and the skill's body as instructions."""
        self._model = model
        self._model_name = model_name
        self._skill = skill

    async def write(self, found: Sequence[dict[str, Any]]) -> Summary:
        """The summary of ``found`` (newest first); falls back on failure."""
        from ai_api.guard import output  # noqa: PLC0415

        data = [
            {
                **{k: row[k] for k in COLUMNS if k != "feed_date"},
                "feed_date": row["feed_date"].isoformat(),
                **rates(row),
            }
            for row in found
        ]
        messages = [
            (
                "system",
                "You write the weekly vendor summary for analysts. Follow "
                "these instructions exactly:\n\n" + self._skill + "\n\nUse "
                "only the numbers in the data block. Never give investment "
                "advice.",
            ),
            (
                "human",
                "<scorecard_data>\n"
                + json.dumps(data, indent=1)
                + "\n</scorecard_data>\nWrite the summary.",
            ),
        ]
        try:
            answer = await self._model.ainvoke(messages)
            text = str(answer.content).strip()
        except Exception as e:  # noqa: BLE001 - the numbers still stand.
            _log.warning("scorecard summary failed: %r", e)
            text = ""
        words = len(text.split())
        if not text or words > 200 or output.investment_advice(text):
            return Summary(fallback_summary(found), "fallback", "")
        return Summary(text, "llm", self._model_name)
