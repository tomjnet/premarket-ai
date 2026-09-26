"""Production (increment 6): the scheduler's record of every job and SLA.

``ai.schedule_run`` has one row per scheduled job run (``corpus``,
``pipeline``, ``brief``, ``refresh``, ``expire``, ``scorecard``,
``retention``) and per SLA check (``sla-ingest``, ``sla-backlog``,
``sla-verify``, ``sla-brief``). ``make -C python sla`` and the admin page
read it; "every SLA green" means every ``sla-*`` row of a trading day is
``OK``.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ai.schedule_run (
          id           bigserial PRIMARY KEY,
          feed_date    date NOT NULL,
          job          text NOT NULL,
          run_mode     text NOT NULL
                       CHECK (run_mode IN ('production', 'demo', 'manual')),
          -- Jobs: RUNNING, DONE, FAILED, SKIPPED. SLA checks: OK, BREACHED.
          status       text NOT NULL
                       CHECK (status IN ('RUNNING', 'DONE', 'FAILED',
                                         'SKIPPED', 'OK', 'BREACHED')),
          started_at   timestamptz NOT NULL DEFAULT now(),
          finished_at  timestamptz,
          detail       text NOT NULL DEFAULT ''
        )
    """)
    op.execute(
        "CREATE INDEX schedule_run_feed_date_idx"
        " ON ai.schedule_run (feed_date, job, started_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE ai.schedule_run")
