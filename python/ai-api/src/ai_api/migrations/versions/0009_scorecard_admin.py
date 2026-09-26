"""Production (increment 6): the vendor scorecard and the admin settings.

- ``ai.vendor_scorecard``: one row per feed date, written by
  ``ai-api scorecard`` (the scheduler at 09:35 ET, after the reviews
  expired, and ``make -C python demo``). A snapshot, so the numbers for the
  vendor stay as they were at the market open. Billable items = unique
  items that are VERIFIED or UNVERIFIED.
- ``ai.app_setting``: settings an ADMIN changes at runtime (the cloud
  switches of the LLM settings page). The API mirrors them to Redis, where
  the worker's cloud budget reads them.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ai.vendor_scorecard (
          feed_date            date PRIMARY KEY,
          computed_at          timestamptz NOT NULL DEFAULT now(),
          received             integer NOT NULL,
          unique_items         integer NOT NULL,
          duplicates           integer NOT NULL,
          dup_url              integer NOT NULL,
          dup_exact            integer NOT NULL,
          dup_near             integer NOT NULL,
          dup_paraphrase       integer NOT NULL,
          stale                integer NOT NULL,
          verified             integer NOT NULL,
          unverified           integer NOT NULL,
          misleading           integer NOT NULL,
          fake                 integer NOT NULL,
          failed               integer NOT NULL,
          pending_review       integer NOT NULL,
          injection            integer NOT NULL,
          -- Independent sources (filings, other outlets) linked per unique
          -- verified item.
          avg_corroboration    real NOT NULL,
          reviewed             integer NOT NULL,
          overridden           integer NOT NULL,
          billable             integer NOT NULL,
          contracted           integer NOT NULL,
          -- Cloud LLM spend of that (UTC) day, from the budget counter.
          cloud_cost_usd       real NOT NULL DEFAULT 0
        )
    """)
    op.execute("""
        CREATE TABLE ai.app_setting (
          key         text PRIMARY KEY CHECK (key ~ '^[a-z][a-z_.]{0,63}$'),
          value       jsonb NOT NULL,
          updated_by  text NOT NULL,
          updated_at  timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE ai.app_setting")
    op.execute("DROP TABLE ai.vendor_scorecard")
