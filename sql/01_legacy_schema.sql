-- premarket-ai: legacy schema (increment 0).
-- Owned by the C++11 legacy ingester (cpp/legacy). Runs once, when the
-- postgres volume is first created (docker-entrypoint-initdb.d).

CREATE SCHEMA IF NOT EXISTS legacy;

-- Company master used by the PDF report to print company names.
CREATE TABLE IF NOT EXISTS legacy.companies (
  ticker      text PRIMARY KEY,
  name        text NOT NULL,
  sector      text NOT NULL
);

-- One row per ingest run (the AI side waits on status = 'DONE' from inc 2).
CREATE TABLE IF NOT EXISTS legacy.ingest_run (
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
  -- Per-item processing latency (parse + normalize + hash), microseconds.
  p50_us          bigint,
  p99_us          bigint,
  p999_us         bigint,
  total_ms        bigint,
  error           text
);

CREATE INDEX IF NOT EXISTS ingest_run_feed_date_idx
  ON legacy.ingest_run (feed_date, started_at DESC);

-- Every vendor item is stored. Duplicates are flagged, never dropped, so the
-- AI app and the vendor scorecard see all of them.
CREATE TABLE IF NOT EXISTS legacy.vendor_news_raw (
  id              bigserial PRIMARY KEY,
  run_id          bigint      NOT NULL REFERENCES legacy.ingest_run (run_id),
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
  ON legacy.vendor_news_raw (feed_date);
CREATE INDEX IF NOT EXISTS vendor_news_raw_hash_idx
  ON legacy.vendor_news_raw (content_hash, feed_date);
