-- premarket-ai: ingest schema (increment 2).
-- Owned by the C++20 ingester (cpp/ingest), which runs in parallel (shadow)
-- with the legacy ingester on the same feed. Runs once, when the postgres
-- volume is first created (docker-entrypoint-initdb.d), and again before
-- every `premarket-ingest ingest` / `parity`, so an existing database gets
-- it too. Idempotent: IF NOT EXISTS everywhere.

CREATE SCHEMA IF NOT EXISTS ingest;

-- One row per ingest run. Same columns as legacy.ingest_run, plus queue-wait
-- percentiles and stage timings.
CREATE TABLE IF NOT EXISTS ingest.ingest_run (
  run_id          bigserial PRIMARY KEY,
  feed_date       date        NOT NULL,
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz,
  status          text        NOT NULL DEFAULT 'RUNNING'
                  CHECK (status IN ('RUNNING', 'DONE', 'FAILED')),
  rows_received   integer     NOT NULL DEFAULT 0,
  rows_inserted   integer     NOT NULL DEFAULT 0,
  dups            integer     NOT NULL DEFAULT 0,
  workers         integer     NOT NULL DEFAULT 0,
  -- Per-item processing latency (extract + validate + normalize + hash),
  -- microseconds. Same meaning as legacy.
  p50_us          bigint,
  p99_us          bigint,
  p999_us         bigint,
  total_ms        bigint,
  error           text,
  -- Per-item queue wait (enqueue -> dequeue), microseconds.
  wait_p50_us     bigint,
  wait_p99_us     bigint,
  wait_p999_us    bigint,
  -- Stage timings of the run.
  fetch_ms        bigint,
  parse_us        bigint,
  dedup_us        bigint,
  copy_ms         bigint
);

CREATE INDEX IF NOT EXISTS ingest_run_feed_date_idx
  ON ingest.ingest_run (feed_date, started_at DESC);

-- Shadow of legacy.vendor_news_raw: same columns and constraints, so the
-- parity job can compare them row for row.
CREATE TABLE IF NOT EXISTS ingest.vendor_news_raw (
  id              bigserial PRIMARY KEY,
  run_id          bigint      NOT NULL REFERENCES ingest.ingest_run (run_id),
  feed_date       date        NOT NULL,
  vendor_item_id  text        NOT NULL,
  headline        text        NOT NULL,
  body            text        NOT NULL,
  source_url      text        NOT NULL,
  source_domain   text        NOT NULL,
  published_at    timestamptz NOT NULL,
  tickers         text[]      NOT NULL DEFAULT '{}',
  synthetic       boolean     NOT NULL DEFAULT true,
  -- SHA-256 (hex) of the normalized headline + body.
  content_hash    char(64)    NOT NULL,
  is_dup          boolean     NOT NULL DEFAULT false,
  -- vendor_item_id of the first copy (same feed or earlier feed).
  dup_of          text,
  ingested_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (feed_date, vendor_item_id)
);

CREATE INDEX IF NOT EXISTS vendor_news_raw_feed_date_idx
  ON ingest.vendor_news_raw (feed_date);
CREATE INDEX IF NOT EXISTS vendor_news_raw_hash_idx
  ON ingest.vendor_news_raw (content_hash, feed_date);

-- One row per parity check of legacy.vendor_news_raw vs
-- ingest.vendor_news_raw for a day. `sample` holds up to 20 differences:
-- [{"vendor_item_id": ..., "columns": [...]}], where a column list of
-- ["missing_in_legacy"] or ["missing_in_modern"] marks a missing row.
CREATE TABLE IF NOT EXISTS ingest.parity_run (
  id              bigserial PRIMARY KEY,
  feed_date       date        NOT NULL,
  checked_at      timestamptz NOT NULL DEFAULT now(),
  legacy_run_id   bigint,
  modern_run_id   bigint,
  legacy_rows     integer,
  modern_rows     integer,
  differences     integer     NOT NULL,
  status          text        NOT NULL CHECK (status IN ('PASS', 'FAIL')),
  sample          jsonb       NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS parity_run_feed_date_idx
  ON ingest.parity_run (feed_date, checked_at DESC);
