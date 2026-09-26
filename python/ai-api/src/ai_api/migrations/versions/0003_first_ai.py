"""First AI (increment 3): AI runs, per-item results, the trusted corpus.

- ``ai.ai_run``: one row per ``ai-api enrich`` run of a feed date.
- ``ai.news_ai``: what the AI steps found for an item: guard and language
  flags, the L3 conflict evidence, the summary and sentiment.
- ``ai.entity`` / ``ai.claim``: the extracted companies and atomic claims
  (increment 4 checks each claim).
- ``ai.news_embedding``: the L3 embedding of each unique item, so the Redis
  vector index can be rebuilt without calling the model again.
- ``ai.document`` / ``ai.chunk``: the trusted corpus (EDGAR filings and
  company facts, Fed and SEC releases). Postgres keeps the chunk text; the
  vector store (ChromaDB in increments 3 to 5) is an index rebuilt from it.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ai.ai_run (
          run_id          bigserial PRIMARY KEY,
          feed_date       date NOT NULL,
          started_at      timestamptz NOT NULL DEFAULT now(),
          finished_at     timestamptz,
          status          text NOT NULL DEFAULT 'RUNNING'
                          CHECK (status IN ('RUNNING', 'DONE', 'FAILED')),
          -- Unique items after the rules, then after L3.
          items           integer NOT NULL DEFAULT 0,
          paraphrases     integer NOT NULL DEFAULT 0,
          conflicts       integer NOT NULL DEFAULT 0,
          injections      integer NOT NULL DEFAULT 0,
          summarized      integer NOT NULL DEFAULT 0,
          fallbacks       integer NOT NULL DEFAULT 0,
          skipped         integer NOT NULL DEFAULT 0,
          failed          integer NOT NULL DEFAULT 0,
          model           text NOT NULL,
          embed_model     text NOT NULL,
          prompt_version  text NOT NULL,
          llm_ms          bigint,
          total_ms        bigint,
          error           text
        )
    """)
    op.execute(
        "CREATE INDEX ai_run_feed_date_idx"
        " ON ai.ai_run (feed_date, started_at DESC)"
    )
    op.execute("""
        CREATE TABLE ai.news_ai (
          news_id         bigint PRIMARY KEY
                          REFERENCES ai.news_item (id) ON DELETE CASCADE,
          run_id          bigint NOT NULL REFERENCES ai.ai_run (run_id),
          -- DONE: summarized; SKIPPED: not English; DUPLICATE: an L3
          -- paraphrase; FAILED: the model call failed.
          status          text NOT NULL
                          CHECK (status IN ('DONE', 'SKIPPED', 'DUPLICATE',
                                            'FAILED')),
          reason_codes    text[] NOT NULL DEFAULT '{}',
          evidence        jsonb NOT NULL DEFAULT '[]',
          summary         text,
          sentiment       text CHECK (sentiment IN ('bullish', 'neutral',
                                                    'bearish')),
          -- llm, or fallback (the story's lead sentence).
          summary_source  text CHECK (summary_source IN ('llm', 'fallback')),
          model           text NOT NULL,
          prompt_version  text NOT NULL,
          error           text,
          enriched_at     timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE ai.entity (
          news_id  bigint NOT NULL
                   REFERENCES ai.news_item (id) ON DELETE CASCADE,
          seq      smallint NOT NULL,
          name     text NOT NULL,
          ticker   text,
          PRIMARY KEY (news_id, seq)
        )
    """)
    op.execute("CREATE INDEX entity_ticker_idx ON ai.entity (ticker)")
    op.execute("""
        CREATE TABLE ai.claim (
          news_id  bigint NOT NULL
                   REFERENCES ai.news_item (id) ON DELETE CASCADE,
          seq      smallint NOT NULL,
          text     text NOT NULL,
          PRIMARY KEY (news_id, seq)
        )
    """)
    op.execute("""
        CREATE TABLE ai.news_embedding (
          news_id      bigint PRIMARY KEY
                       REFERENCES ai.news_item (id) ON DELETE CASCADE,
          model        text NOT NULL,
          dims         integer NOT NULL,
          text_sha256  text NOT NULL,
          embedding    real[] NOT NULL,
          created_at   timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE ai.document (
          id              bigserial PRIMARY KEY,
          source          text NOT NULL
                          CHECK (source IN ('edgar_8k', 'edgar_ex99',
                                            'xbrl_facts', 'fed_press',
                                            'sec_press')),
          url             text NOT NULL UNIQUE,
          title           text NOT NULL,
          ticker          text,
          cik             bigint,
          published_at    timestamptz,
          fetched_at      timestamptz NOT NULL DEFAULT now(),
          content_sha256  text NOT NULL,
          text            text NOT NULL
        )
    """)
    op.execute("CREATE INDEX document_ticker_idx ON ai.document (ticker)")
    op.execute("""
        CREATE TABLE ai.chunk (
          id           bigserial PRIMARY KEY,
          document_id  bigint NOT NULL
                       REFERENCES ai.document (id) ON DELETE CASCADE,
          seq          integer NOT NULL,
          text         text NOT NULL,
          metadata     jsonb NOT NULL DEFAULT '{}',
          -- Set when the chunk is in the vector store (with that model).
          embed_model  text,
          indexed_at   timestamptz,
          UNIQUE (document_id, seq)
        )
    """)


def downgrade() -> None:
    for name in (
        "chunk",
        "document",
        "news_embedding",
        "claim",
        "entity",
        "news_ai",
        "ai_run",
    ):
        op.execute(f"DROP TABLE ai.{name}")
