"""Agents and Skills (increment 5): the pre-market brief and long-term memory.

- ``ai.brief``: one row per brief of a feed date and edition (``morning``
  at 07:15 ET, ``refresh`` at 09:00 ET). The deterministic part (which items
  go in, their sections and the counts) and the checked overview live in
  it; the web page and the MCP tool ``get_brief`` read it.
- Schema ``memory``: the LangGraph Postgres store (long-term memory: each
  user's watchlist). Its tables are created by ``ai-api init``, like the
  checkpointer's in ``graph``.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS memory")
    op.execute("""
        CREATE TABLE ai.brief (
          brief_id         bigserial PRIMARY KEY,
          feed_date        date NOT NULL,
          -- morning: 07:15 ET; refresh: 09:00 ET, with the items analysts
          -- reviewed since the morning edition.
          edition          text NOT NULL
                           CHECK (edition IN ('morning', 'refresh')),
          status           text NOT NULL DEFAULT 'QUEUED'
                           CHECK (status IN ('QUEUED', 'RUNNING', 'DONE',
                                             'FAILED')),
          requested_by     text,
          requested_at     timestamptz NOT NULL DEFAULT now(),
          started_at       timestamptz,
          finished_at      timestamptz,
          verify_run_id    bigint REFERENCES ai.verify_run (run_id)
                           ON DELETE SET NULL,
          -- The overview a model wrote (checked: citations, no advice), or
          -- the deterministic one when the model's failed the checks.
          overview         text NOT NULL DEFAULT '',
          overview_source  text CHECK (overview_source IN ('llm',
                                                           'fallback')),
          citations        integer[] NOT NULL DEFAULT '{}',
          -- Items (numbered for citations), sections and counts.
          content          jsonb NOT NULL DEFAULT '{}'::jsonb,
          verified         integer NOT NULL DEFAULT 0,
          unconfirmed      integer NOT NULL DEFAULT 0,
          pending_review   integer NOT NULL DEFAULT 0,
          excluded         integer NOT NULL DEFAULT 0,
          model            text,
          prompt_version   text,
          cloud            boolean NOT NULL DEFAULT false,
          cost_usd         real NOT NULL DEFAULT 0,
          total_ms         bigint,
          error            text
        )
    """)
    op.execute(
        "CREATE INDEX brief_feed_date_idx"
        " ON ai.brief (feed_date, requested_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE ai.brief")
    op.execute("DROP SCHEMA IF EXISTS memory CASCADE")
