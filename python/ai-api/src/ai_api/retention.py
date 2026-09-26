"""``ai-api retention``: the nightly 90-day cleanup (RETENTION_DAYS).

Deletes, as the database owner and in one transaction, everything the AI
side decided about feed dates older than the cutoff: verify runs (with
their verdicts, review tasks and LangGraph checkpoints), briefs, news items
(with duplicate links, rule checks, AI results, entities, claims,
embeddings and evidence), the rule, AI and scheduler runs, and audit log
rows older than the cutoff.

Kept on purpose:

- ``ai.eval_example``: the analysts' overrides are the learning loop's
  labeled examples (their ``news_id`` becomes NULL, the text stays).
- The raw vendor news (``ingest.*`` / ``legacy.*``): owned by the
  ingesters, not by the AI side.
- The trusted corpus (``ai.document`` / ``ai.chunk``): ``ai-api corpus``
  keeps its own 12-month window.

A documented lab simplification: this isn't a regulatory-grade audit trail
(see the README's "Audit" note).
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Any

import psycopg

DEFAULT_DAYS = 90


@dataclasses.dataclass(frozen=True)
class Purged:
    """Rows deleted per table."""

    cutoff: datetime.date
    counts: dict[str, int]

    def line(self) -> str:
        """One log line."""
        parts = ", ".join(f"{k} {v}" for k, v in self.counts.items())
        return f"older than {self.cutoff}: {parts}"


# (table, statement). Order matters: items before the runs they reference
# without a cascade (ai.news_ai -> ai.ai_run), checkpoints before the runs
# whose ids name their threads. A table that doesn't exist (the LangGraph
# tables before the first ``ai-api init``) is skipped.
_STATEMENTS: tuple[tuple[str, str], ...] = (
    (
        "graph.checkpoints",
        "DELETE FROM graph.checkpoints WHERE thread_id LIKE 'verify-%%'"
        " AND split_part(thread_id, '-', 2)::bigint IN"
        " (SELECT run_id FROM ai.verify_run WHERE feed_date < %(cutoff)s)",
    ),
    (
        "graph.checkpoint_writes",
        "DELETE FROM graph.checkpoint_writes WHERE thread_id LIKE 'verify-%%'"
        " AND split_part(thread_id, '-', 2)::bigint IN"
        " (SELECT run_id FROM ai.verify_run WHERE feed_date < %(cutoff)s)",
    ),
    (
        "graph.checkpoint_blobs",
        "DELETE FROM graph.checkpoint_blobs WHERE thread_id LIKE 'verify-%%'"
        " AND split_part(thread_id, '-', 2)::bigint IN"
        " (SELECT run_id FROM ai.verify_run WHERE feed_date < %(cutoff)s)",
    ),
    ("ai.brief", "DELETE FROM ai.brief WHERE feed_date < %(cutoff)s"),
    ("ai.verify_run", "DELETE FROM ai.verify_run WHERE feed_date < %(cutoff)s"),
    ("ai.news_item", "DELETE FROM ai.news_item WHERE feed_date < %(cutoff)s"),
    ("ai.ai_run", "DELETE FROM ai.ai_run WHERE feed_date < %(cutoff)s"),
    ("ai.rule_run", "DELETE FROM ai.rule_run WHERE feed_date < %(cutoff)s"),
    (
        "ai.schedule_run",
        "DELETE FROM ai.schedule_run WHERE feed_date < %(cutoff)s",
    ),
    (
        "ai.vendor_scorecard",
        "DELETE FROM ai.vendor_scorecard WHERE feed_date < %(cutoff)s",
    ),
    (
        "ai.audit_log",
        "DELETE FROM ai.audit_log WHERE at < %(cutoff)s::timestamptz",
    ),
)


def cutoff_for(today: datetime.date, days: int) -> datetime.date:
    """The first feed date kept.

    Args:
        today: The day the cleanup runs.
        days: RETENTION_DAYS.

    Returns:
        ``today - days``; everything before it is deleted.

    Raises:
        ValueError: ``days`` isn't positive.
    """
    if days <= 0:
        raise ValueError("RETENTION_DAYS must be positive")
    return today - datetime.timedelta(days=days)


def purge(conn: psycopg.Connection[Any], cutoff: datetime.date) -> Purged:
    """Deletes what is older than ``cutoff`` (one transaction).

    Args:
        conn: An owner connection (not autocommit).
        cutoff: The first feed date kept.

    Returns:
        The rows deleted per table.
    """
    counts: dict[str, int] = {}
    with conn.transaction():
        for table, statement in _STATEMENTS:
            if not _exists(conn, table):
                continue
            cur = conn.execute(statement, {"cutoff": cutoff})
            counts[table] = cur.rowcount
    return Purged(cutoff, counts)


def _exists(conn: psycopg.Connection[Any], table: str) -> bool:
    row = conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()
    return row is not None and row[0] is not None
