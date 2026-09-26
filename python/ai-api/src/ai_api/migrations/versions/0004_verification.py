"""AI verification (increment 4): verdicts, evidence, the review queue.

- ``ai.verdict``: the four verdicts, an enum.
- ``ai.verify_run``: one row per verification run of a feed date
  (``POST /runs``, ``ai-api verify``); the worker jobs count into it.
- ``ai.verification``: the verdict of one unique item, with the rule-based
  and the judge's verdicts it came from, the review state and the impact.
- ``ai.evidence``: why, one row per finding (ids E1, E2... in the prompt).
- ``ai.review_task``: the human review queue (PENDING -> APPROVED,
  OVERRIDDEN or EXPIRED).
- ``ai.eval_example``: every override, as a new labeled example. It is
  never purged by the retention job (the learning loop keeps it).
- Schema ``graph``: the LangGraph Postgres checkpointer's tables (created
  by ``ai-api init``), so a graph waiting for review survives restarts.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE ai.verdict AS ENUM"
        " ('VERIFIED', 'UNVERIFIED', 'MISLEADING', 'FAKE')"
    )
    op.execute("CREATE SCHEMA IF NOT EXISTS graph")
    op.execute("""
        CREATE TABLE ai.verify_run (
          run_id          bigserial PRIMARY KEY,
          feed_date       date NOT NULL,
          status          text NOT NULL DEFAULT 'QUEUED'
                          CHECK (status IN ('QUEUED', 'RUNNING', 'DONE',
                                            'FAILED')),
          requested_by    text,
          requested_at    timestamptz NOT NULL DEFAULT now(),
          started_at      timestamptz,
          finished_at     timestamptz,
          -- Unique items queued, and how far the workers are.
          total           integer NOT NULL DEFAULT 0,
          done            integer NOT NULL DEFAULT 0,
          failed          integer NOT NULL DEFAULT 0,
          verified        integer NOT NULL DEFAULT 0,
          unverified      integer NOT NULL DEFAULT 0,
          misleading      integer NOT NULL DEFAULT 0,
          fake            integer NOT NULL DEFAULT 0,
          pending_review  integer NOT NULL DEFAULT 0,
          escalated       integer NOT NULL DEFAULT 0,
          model           text,
          prompt_version  text,
          total_ms        bigint,
          error           text
        )
    """)
    op.execute(
        "CREATE INDEX verify_run_feed_date_idx"
        " ON ai.verify_run (feed_date, requested_at DESC)"
    )
    op.execute("""
        CREATE TABLE ai.verification (
          news_id           bigint PRIMARY KEY
                            REFERENCES ai.news_item (id) ON DELETE CASCADE,
          run_id            bigint NOT NULL
                            REFERENCES ai.verify_run (run_id)
                            ON DELETE CASCADE,
          -- PENDING_REVIEW: waiting in the review queue (the graph is
          -- interrupted); DONE: final; FAILED: the graph failed.
          status            text NOT NULL
                            CHECK (status IN ('PENDING_REVIEW', 'DONE',
                                              'FAILED')),
          verdict           ai.verdict,
          confidence        real CHECK (confidence BETWEEN 0 AND 1),
          reason_codes      text[] NOT NULL DEFAULT '{}',
          rationale         text NOT NULL DEFAULT '',
          -- What the verdict came from: the deterministic checks, then the
          -- LLM judge (local, or the cloud model when escalated).
          rule_verdict      ai.verdict,
          rule_confidence   real,
          judge_verdict     ai.verdict,
          judge_confidence  real,
          judge_model       text,
          escalated         boolean NOT NULL DEFAULT false,
          review_status     text CHECK (review_status IN ('PENDING',
                                        'APPROVED', 'OVERRIDDEN',
                                        'EXPIRED')),
          review_reasons    text[] NOT NULL DEFAULT '{}',
          -- Market impact: relevance of the news kind x company size.
          relevance         real,
          impact            text CHECK (impact IN ('low', 'medium', 'high')),
          impact_score      real,
          thread_id         text NOT NULL,
          prompt_version    text NOT NULL,
          error             text,
          verified_at       timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now(),
          CHECK (status = 'FAILED' OR verdict IS NOT NULL)
        )
    """)
    op.execute("CREATE INDEX verification_run_idx ON ai.verification (run_id)")
    op.execute("""
        CREATE TABLE ai.evidence (
          news_id     bigint NOT NULL
                      REFERENCES ai.news_item (id) ON DELETE CASCADE,
          seq         smallint NOT NULL,
          -- entity, source, corroboration, claim, style, rules, ai, guard,
          -- language, ml, judge, review.
          check_type  text NOT NULL,
          code        text,
          message     text NOT NULL,
          -- Where it came from: registry, reputation, filing, web, prices,
          -- rules, model...; plus a link for filings and web results.
          source      text NOT NULL DEFAULT '',
          url         text,
          title       text,
          PRIMARY KEY (news_id, seq)
        )
    """)
    op.execute("""
        CREATE TABLE ai.review_task (
          id             bigserial PRIMARY KEY,
          news_id        bigint NOT NULL
                         REFERENCES ai.news_item (id) ON DELETE CASCADE,
          run_id         bigint NOT NULL
                         REFERENCES ai.verify_run (run_id) ON DELETE CASCADE,
          status         text NOT NULL DEFAULT 'PENDING'
                         CHECK (status IN ('PENDING', 'APPROVED',
                                           'OVERRIDDEN', 'EXPIRED')),
          -- low_confidence, judge_disagrees, guard_unsafe,
          -- unsupported_language.
          reasons        text[] NOT NULL DEFAULT '{}',
          ai_verdict     ai.verdict NOT NULL,
          ai_confidence  real NOT NULL,
          final_verdict  ai.verdict,
          impact_score   real NOT NULL DEFAULT 0,
          thread_id      text NOT NULL,
          reviewer       text,
          comment        text,
          created_at     timestamptz NOT NULL DEFAULT now(),
          decided_at     timestamptz,
          UNIQUE (news_id, run_id),
          CHECK (status <> 'OVERRIDDEN'
                 OR (final_verdict IS NOT NULL
                     AND length(coalesce(comment, '')) > 0))
        )
    """)
    op.execute(
        "CREATE INDEX review_task_queue_idx"
        " ON ai.review_task (status, impact_score DESC)"
    )
    op.execute("""
        CREATE TABLE ai.eval_example (
          id                bigserial PRIMARY KEY,
          news_id           bigint REFERENCES ai.news_item (id)
                            ON DELETE SET NULL,
          feed_date         date NOT NULL,
          vendor_item_id    text NOT NULL,
          headline          text NOT NULL,
          body              text NOT NULL,
          source_domain     text NOT NULL,
          tickers           text[] NOT NULL DEFAULT '{}',
          label_verdict     ai.verdict NOT NULL,
          previous_verdict  ai.verdict NOT NULL,
          reason_codes      text[] NOT NULL DEFAULT '{}',
          reviewer          text NOT NULL,
          comment           text NOT NULL,
          created_at        timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    for name in (
        "eval_example",
        "review_task",
        "evidence",
        "verification",
        "verify_run",
    ):
        op.execute(f"DROP TABLE ai.{name}")
    op.execute("DROP SCHEMA IF EXISTS graph CASCADE")
    op.execute("DROP TYPE ai.verdict")
