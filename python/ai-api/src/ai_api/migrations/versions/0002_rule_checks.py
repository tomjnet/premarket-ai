"""Rule checks (increment 2): the raw-news views, dedup links, rule results.

- ``ai.v_raw_news`` / ``ai.v_ingest_run``: the only way the AI side reads raw
  news (the strangler-fig seam). They point at ``legacy.*`` until the C++20
  ingester replaces the legacy one in increment 6.
- ``ai.news_item``: a stable id per vendor item, keyed by (feed date, vendor
  id), so re-ingesting a day (new raw row ids) keeps every AI result.
- ``ai.duplicate_link``, ``ai.rule_check``, ``ai.rule_run``: the decisions.
- ``ai.ticker_registry``: the SEC ticker registry cache.
- ``ai.source_reputation``: domain reputations (admin-editable later).

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE VIEW ai.v_ingest_run AS
        SELECT run_id, feed_date, started_at, finished_at, status,
               rows_received, rows_inserted, dups, workers, error
        FROM legacy.ingest_run
    """)
    op.execute("""
        CREATE VIEW ai.v_raw_news AS
        SELECT id, run_id, feed_date, vendor_item_id, headline, body,
               source_url, source_domain, published_at, tickers, synthetic,
               content_hash, is_dup, dup_of, ingested_at
        FROM legacy.vendor_news_raw
    """)
    op.execute("""
        CREATE TABLE ai.news_item (
          id              bigserial PRIMARY KEY,
          feed_date       date NOT NULL,
          vendor_item_id  text NOT NULL,
          first_seen_at   timestamptz NOT NULL DEFAULT now(),
          UNIQUE (feed_date, vendor_item_id)
        )
    """)
    op.execute("""
        CREATE TABLE ai.duplicate_link (
          news_id       bigint PRIMARY KEY
                        REFERENCES ai.news_item (id) ON DELETE CASCADE,
          canonical_id  bigint NOT NULL
                        REFERENCES ai.news_item (id) ON DELETE CASCADE,
          dup_type      text NOT NULL
                        CHECK (dup_type IN ('url', 'exact', 'near',
                                            'paraphrase')),
          level         text NOT NULL CHECK (level IN ('L0', 'L1', 'L2', 'L3')),
          -- L2: SimHash Hamming distance; L3 (increment 3): cosine.
          score         real,
          -- The original is from an earlier feed date: re-served old news.
          stale         boolean NOT NULL DEFAULT false,
          created_at    timestamptz NOT NULL DEFAULT now(),
          CHECK (news_id <> canonical_id)
        )
    """)
    op.execute(
        "CREATE INDEX duplicate_link_canonical_idx"
        " ON ai.duplicate_link (canonical_id)"
    )
    op.execute("""
        CREATE TABLE ai.rule_check (
          news_id        bigint PRIMARY KEY
                         REFERENCES ai.news_item (id) ON DELETE CASCADE,
          reason_codes   text[] NOT NULL DEFAULT '{}',
          evidence       jsonb NOT NULL DEFAULT '[]',
          rules_version  text NOT NULL,
          checked_at     timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE ai.rule_run (
          run_id            bigserial PRIMARY KEY,
          feed_date         date NOT NULL,
          started_at        timestamptz NOT NULL DEFAULT now(),
          finished_at       timestamptz,
          status            text NOT NULL DEFAULT 'RUNNING'
                            CHECK (status IN ('RUNNING', 'DONE', 'FAILED')),
          items             integer NOT NULL DEFAULT 0,
          duplicates        integer NOT NULL DEFAULT 0,
          stale             integer NOT NULL DEFAULT 0,
          flagged           integer NOT NULL DEFAULT 0,
          by_type           jsonb NOT NULL DEFAULT '{}',
          reason_counts     jsonb NOT NULL DEFAULT '{}',
          registry_tickers  integer,
          rules_version     text NOT NULL,
          -- native (C++20 premarket_fastpath) or python (reference).
          backend           text NOT NULL,
          total_ms          bigint,
          error             text
        )
    """)
    op.execute(
        "CREATE INDEX rule_run_feed_date_idx"
        " ON ai.rule_run (feed_date, started_at DESC)"
    )
    op.execute("""
        CREATE TABLE ai.ticker_registry (
          ticker        text PRIMARY KEY,
          cik           bigint NOT NULL,
          title         text NOT NULL,
          refreshed_at  timestamptz NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE ai.source_reputation (
          domain      text PRIMARY KEY CHECK (domain = lower(domain)),
          tier        text NOT NULL
                      CHECK (tier IN ('trusted', 'neutral', 'low', 'blocked')),
          reputation  real NOT NULL CHECK (reputation BETWEEN 0 AND 1),
          note        text NOT NULL DEFAULT '',
          updated_at  timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    for name in (
        "source_reputation",
        "ticker_registry",
        "rule_run",
        "rule_check",
        "duplicate_link",
        "news_item",
    ):
        op.execute(f"DROP TABLE ai.{name}")
    op.execute("DROP VIEW ai.v_raw_news")
    op.execute("DROP VIEW ai.v_ingest_run")
