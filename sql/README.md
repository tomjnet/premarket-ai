# sql/: legacy database

PostgreSQL runs these init scripts once, when the `pgdata` volume is first created:

| File | What it does |
|---|---|
| `01_legacy_schema.sql` | `legacy` schema: `companies`, `ingest_run`, `vendor_news_raw` |
| `02_legacy_seed.sql` | Seeds `legacy.companies` with 20 large US companies |

PostgreSQL's init step skips this README (it runs only `*.sql`, `*.sql.gz` and `*.sh`). To re-run the scripts, delete the volume with `make -C python reset`. **This erases all data.**

| Table | Contents |
|---|---|
| `legacy.companies` | Company master (ticker, name, sector). The PDF uses it to print names. |
| `legacy.ingest_run` | One row per ingest run: status, counts, p50/p99/p99.9 latency, errors |
| `legacy.vendor_news_raw` | Every vendor item. Duplicates are flagged (`is_dup`, `dup_of`), never dropped. |

## Connect

psql runs inside the postgres container, so there's nothing to install. From Ubuntu WSL:

```bash
cd ~/src/premarket-ai && make -C python psql
```

This runs `podman compose exec postgres psql -U premarket -d premarket`. Type `\q` to quit.

To run one query without opening the shell:

```bash
cd ~/src/premarket-ai && podman compose exec -T postgres psql -U premarket -d premarket -c "SELECT run_id, feed_date, status, rows_received, dups FROM legacy.ingest_run ORDER BY run_id DESC LIMIT 5;"
```

The stack must be running (`make -C python up`). The queries below use the demo date `2026-09-24`; change it to any day you ingested.

## psql basics

```sql
\dn                         -- schemas
\dt legacy.*                -- tables in the legacy schema
\d legacy.vendor_news_raw   -- columns of a table
\x auto                     -- wide rows display vertically
```

## `legacy.vendor_news_raw`

**Items and duplicates per day**
```sql
SELECT feed_date, count(*) AS items,
       count(*) FILTER (WHERE is_dup) AS dups,
       count(*) FILTER (WHERE NOT is_dup) AS in_pdf
FROM legacy.vendor_news_raw
GROUP BY feed_date
ORDER BY feed_date;
```

**Each duplicate next to the item it copies.** A `dup_of` from an earlier day is a stale copy.
```sql
SELECT d.vendor_item_id AS duplicate, d.dup_of AS original,
       o.feed_date AS original_day,
       CASE WHEN o.feed_date < d.feed_date THEN 'stale' ELSE 'same day' END AS kind,
       left(d.headline, 70) AS headline
FROM legacy.vendor_news_raw d
LEFT JOIN legacy.vendor_news_raw o ON o.vendor_item_id = d.dup_of
WHERE d.feed_date = '2026-09-24' AND d.is_dup
ORDER BY kind, d.vendor_item_id;
```

**Tickers that aren't in the company master.** These are the fake companies and fake tickers the legacy system never catches.
```sql
SELECT t.ticker, count(*) AS items, min(left(n.headline, 60)) AS example
FROM legacy.vendor_news_raw n
CROSS JOIN LATERAL unnest(n.tickers) AS t(ticker)
LEFT JOIN legacy.companies c ON c.ticker = t.ticker
WHERE n.feed_date = '2026-09-24' AND c.ticker IS NULL
GROUP BY t.ticker
ORDER BY items DESC;
```

**Items per source domain.** `.test` domains are lookalike, spoofed sources.
```sql
SELECT source_domain, count(*) AS items,
       count(*) FILTER (WHERE is_dup) AS dups
FROM legacy.vendor_news_raw
WHERE feed_date = '2026-09-24'
GROUP BY source_domain
ORDER BY items DESC;
```

**Most-mentioned companies**
```sql
SELECT c.ticker, c.name, count(*) AS mentions
FROM legacy.vendor_news_raw n
JOIN legacy.companies c ON c.ticker = ANY (n.tickers)
WHERE n.feed_date = '2026-09-24' AND NOT n.is_dup
GROUP BY c.ticker, c.name
ORDER BY mentions DESC
LIMIT 10;
```

**Items with prompt-injection text.** Increment 4 has to flag these.
```sql
SELECT vendor_item_id, left(headline, 60) AS headline
FROM legacy.vendor_news_raw
WHERE feed_date = '2026-09-24'
  AND (body ILIKE '%ignore previous instructions%' OR body ILIKE '%AI REVIEWERS%');
```

**Read one full story**
```sql
\x on
SELECT vendor_item_id, headline, body, source_url, tickers,
       published_at AT TIME ZONE 'America/New_York' AS published_et,
       content_hash, is_dup, dup_of
FROM legacy.vendor_news_raw
WHERE feed_date = '2026-09-24'
ORDER BY published_at
LIMIT 1;
\x off
```

## `legacy.companies`

**All companies**
```sql
SELECT ticker, name, sector FROM legacy.companies ORDER BY ticker;
```

**Companies per sector**
```sql
SELECT sector, count(*) AS companies, string_agg(ticker, ', ' ORDER BY ticker) AS tickers
FROM legacy.companies
GROUP BY sector
ORDER BY companies DESC;
```

**Companies with no news that day**
```sql
SELECT c.ticker, c.name
FROM legacy.companies c
WHERE NOT EXISTS (
  SELECT 1 FROM legacy.vendor_news_raw n
  WHERE n.feed_date = '2026-09-24' AND c.ticker = ANY (n.tickers))
ORDER BY c.ticker;
```

**News count per sector** (without duplicates)
```sql
SELECT c.sector, count(DISTINCT n.id) AS stories
FROM legacy.vendor_news_raw n
JOIN legacy.companies c ON c.ticker = ANY (n.tickers)
WHERE n.feed_date = '2026-09-24' AND NOT n.is_dup
GROUP BY c.sector
ORDER BY stories DESC;
```

## `legacy.ingest_run`

**Latest runs (the increment 0 "done when" check).** The demo date should show `DONE`, 100 received and 9 dups.
```sql
SELECT run_id, feed_date, status, rows_received, dups, workers,
       p50_us, p99_us, p999_us, total_ms,
       finished_at AT TIME ZONE 'America/New_York' AS finished_et
FROM legacy.ingest_run
ORDER BY run_id DESC
LIMIT 10;
```

**Runs by status**
```sql
SELECT status, count(*) AS runs, min(feed_date) AS first_day, max(feed_date) AS last_day
FROM legacy.ingest_run
GROUP BY status;
```

**Failed runs and why**
```sql
SELECT run_id, feed_date, started_at AT TIME ZONE 'America/New_York' AS started_et, error
FROM legacy.ingest_run
WHERE status = 'FAILED'
ORDER BY run_id DESC;
```

**Latest run per day.** A day ingested twice keeps only its last run's rows.
```sql
SELECT DISTINCT ON (feed_date)
       feed_date, run_id, status, rows_received, dups, total_ms
FROM legacy.ingest_run
ORDER BY feed_date DESC, run_id DESC;
```

**Latency trend.** This is the baseline the C++20 ingester in increment 2 has to beat.
```sql
SELECT run_id, feed_date, workers,
       p50_us, p99_us, p999_us,
       round(p99_us::numeric / nullif(p50_us, 0), 1) AS p99_over_p50,
       total_ms
FROM legacy.ingest_run
WHERE status = 'DONE'
ORDER BY run_id;
```

**Average latency by worker count.** Change `LEGACY_WORKERS` in `.env` (for example 1, then 8) and re-ingest to compare.
```sql
SELECT workers, count(*) AS runs,
       round(avg(p50_us)) AS avg_p50_us,
       round(avg(p99_us)) AS avg_p99_us,
       round(avg(total_ms)) AS avg_total_ms
FROM legacy.ingest_run
WHERE status = 'DONE'
GROUP BY workers
ORDER BY workers;
```

**How long each run took**
```sql
SELECT run_id, feed_date,
       finished_at - started_at AS duration,
       rows_received, dups
FROM legacy.ingest_run
WHERE finished_at IS NOT NULL
ORDER BY run_id DESC
LIMIT 10;
```

**Rows stored vs what the run reported.** The two counts should match. Older runs of a re-ingested day show `stored = 0`, because re-running `ingest` replaces that day's rows.
```sql
SELECT r.run_id, r.feed_date, r.rows_inserted AS reported,
       count(n.id) AS stored,
       r.dups AS reported_dups,
       count(n.id) FILTER (WHERE n.is_dup) AS stored_dups
FROM legacy.ingest_run r
LEFT JOIN legacy.vendor_news_raw n ON n.run_id = r.run_id
WHERE r.status = 'DONE'
GROUP BY r.run_id
ORDER BY r.run_id DESC;
```

## Database overview

**Size and row count of every table**
```sql
SELECT schemaname || '.' || relname AS table_name,
       n_live_tup AS approx_rows,
       pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;
```

**Indexes**
```sql
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'legacy'
ORDER BY tablename, indexname;
```

**Constraints** (primary keys, foreign keys, unique, check)
```sql
SELECT conrelid::regclass AS table_name, conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE connamespace = 'legacy'::regnamespace
ORDER BY table_name, conname;
```

**Database size**
```sql
SELECT pg_size_pretty(pg_database_size('premarket')) AS db_size;
```
