// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/parity.h"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <thread>

#include "absl/log/log.h"
#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "absl/strings/str_cat.h"
#include "common/latency.h"
#include "db/pg_connection.h"
#include "db/repository.h"

namespace premarket::ingest {
namespace {

constexpr int kPollSeconds = 5;
constexpr int64_t kNanosPerSecond = int64_t{1000} * 1000 * 1000;

// Every stored column except id, run_id and ingested_at (which differ by
// design). Differences are listed per item, at most 20 in the sample.
constexpr std::string_view kCompareSql = R"sql(
WITH l AS (
  SELECT * FROM legacy.vendor_news_raw WHERE feed_date = $1::date),
m AS (
  SELECT * FROM ingest.vendor_news_raw WHERE feed_date = $1::date),
diff AS (
  SELECT coalesce(l.vendor_item_id, m.vendor_item_id) AS vendor_item_id,
    CASE
      WHEN l.vendor_item_id IS NULL THEN ARRAY['missing_in_legacy']
      WHEN m.vendor_item_id IS NULL THEN ARRAY['missing_in_modern']
      ELSE array_remove(ARRAY[
        CASE WHEN l.headline IS DISTINCT FROM m.headline
             THEN 'headline' END,
        CASE WHEN l.body IS DISTINCT FROM m.body THEN 'body' END,
        CASE WHEN l.source_url IS DISTINCT FROM m.source_url
             THEN 'source_url' END,
        CASE WHEN l.source_domain IS DISTINCT FROM m.source_domain
             THEN 'source_domain' END,
        CASE WHEN l.published_at IS DISTINCT FROM m.published_at
             THEN 'published_at' END,
        CASE WHEN l.tickers IS DISTINCT FROM m.tickers
             THEN 'tickers' END,
        CASE WHEN l.synthetic IS DISTINCT FROM m.synthetic
             THEN 'synthetic' END,
        CASE WHEN l.content_hash IS DISTINCT FROM m.content_hash
             THEN 'content_hash' END,
        CASE WHEN l.is_dup IS DISTINCT FROM m.is_dup THEN 'is_dup' END,
        CASE WHEN l.dup_of IS DISTINCT FROM m.dup_of THEN 'dup_of' END
      ], NULL)
    END AS columns
  FROM l FULL OUTER JOIN m ON l.vendor_item_id = m.vendor_item_id),
bad AS (
  SELECT vendor_item_id, columns FROM diff WHERE cardinality(columns) > 0)
SELECT
  (SELECT count(*) FROM l),
  (SELECT count(*) FROM m),
  (SELECT count(*) FROM bad),
  coalesce((
    SELECT jsonb_agg(jsonb_build_object('vendor_item_id', vendor_item_id,
                                        'columns', to_jsonb(columns))
                     ORDER BY vendor_item_id)
    FROM (SELECT * FROM bad ORDER BY vendor_item_id LIMIT 20) sample),
    '[]'::jsonb)::text
)sql";

struct LatestRun {
  bool found = false;
  int64_t run_id = 0;
  std::string status;
  int64_t rows = 0;
  int64_t dups = 0;

  std::string Describe() const {
    return found ? absl::StrCat("run ", run_id, " ", status) : "no run";
  }
};

absl::StatusOr<LatestRun> LoadLatestRun(PgConnection* conn,
                                        std::string_view schema,
                                        const std::string& feed_date) {
  PgResult result;
  absl::Status status = conn->ExecParams(
      absl::StrCat("SELECT run_id, status, rows_received, dups FROM ", schema,
                   ".ingest_run WHERE feed_date = $1::date "
                   "ORDER BY started_at DESC, run_id DESC LIMIT 1"),
      {feed_date}, &result);
  if (!status.ok()) return status;
  LatestRun run;
  if (result.rows() == 0) return run;
  run.found = true;
  run.run_id = result.GetInt64(0, 0);
  run.status = result.Get(0, 1);
  run.rows = result.GetInt64(0, 2);
  run.dups = result.GetInt64(0, 3);
  return run;
}

// Polls until both latest runs are DONE. Fails at once on a FAILED run.
absl::Status WaitForRuns(PgConnection* conn, const std::string& feed_date,
                         int wait_s, LatestRun* legacy, LatestRun* modern) {
  const int64_t deadline = NowNanos() + wait_s * kNanosPerSecond;
  while (true) {
    absl::StatusOr<LatestRun> l = LoadLatestRun(conn, "legacy", feed_date);
    if (!l.ok()) return l.status();
    absl::StatusOr<LatestRun> m = LoadLatestRun(conn, "ingest", feed_date);
    if (!m.ok()) return m.status();
    *legacy = *l;
    *modern = *m;
    if (legacy->status == "FAILED" || modern->status == "FAILED") {
      return absl::FailedPreconditionError(
          absl::StrCat("cannot compare ", feed_date, ": legacy ",
                       legacy->Describe(), ", modern ", modern->Describe()));
    }
    if (legacy->status == "DONE" && modern->status == "DONE") {
      return absl::OkStatus();
    }
    const int64_t left = deadline - NowNanos();
    if (left <= 0) {
      return absl::DeadlineExceededError(
          absl::StrCat("timed out after ", wait_s,
                       " s waiting for DONE runs for ", feed_date, ": legacy ",
                       legacy->Describe(), ", modern ", modern->Describe()));
    }
    LOG(INFO) << "waiting for " << feed_date << ": legacy "
              << legacy->Describe() << ", modern " << modern->Describe();
    std::this_thread::sleep_for(
        std::min(std::chrono::nanoseconds(left),
                 std::chrono::nanoseconds(kPollSeconds * kNanosPerSecond)));
  }
}

}  // namespace

absl::Status RunParity(const Config& config, const std::string& feed_date) {
  absl::StatusOr<std::unique_ptr<PgConnection>> conn =
      PgConnection::Connect(config.pg_conninfo);
  if (!conn.ok()) return conn.status();
  PgConnection* db = conn->get();
  absl::Status status = ApplySchemaFile(config.schema_file, db);
  if (!status.ok()) return status;

  LatestRun legacy;
  LatestRun modern;
  status = WaitForRuns(db, feed_date, config.parity_wait_s, &legacy, &modern);
  if (!status.ok()) return status;

  PgResult result;
  status = db->ExecParams(std::string(kCompareSql), {feed_date}, &result);
  if (!status.ok()) return status;
  const int64_t legacy_rows = result.GetInt64(0, 0);
  const int64_t modern_rows = result.GetInt64(0, 1);
  const int64_t differences = result.GetInt64(0, 2);
  const std::string sample(result.Get(0, 3));
  const char* verdict = differences == 0 ? "PASS" : "FAIL";

  PgResult inserted;
  status = db->ExecParams(
      "INSERT INTO ingest.parity_run (feed_date, legacy_run_id, "
      "modern_run_id, legacy_rows, modern_rows, differences, status, sample) "
      "VALUES ($1::date, $2::bigint, $3::bigint, $4::int, $5::int, $6::int, "
      "$7, $8::jsonb) RETURNING id",
      {feed_date, absl::StrCat(legacy.run_id), absl::StrCat(modern.run_id),
       absl::StrCat(legacy_rows), absl::StrCat(modern_rows),
       absl::StrCat(differences), verdict, sample},
      &inserted);
  if (!status.ok()) return status;

  LOG(INFO) << "parity " << feed_date << " " << verdict << " (parity_run "
            << inserted.GetInt64(0, 0) << "): legacy run " << legacy.run_id
            << " " << legacy_rows << " rows " << legacy.dups
            << " dups, modern run " << modern.run_id << " " << modern_rows
            << " rows " << modern.dups << " dups, " << differences
            << " differences";
  if (differences != 0) {
    LOG(ERROR) << "parity differences (first 20): " << sample;
    return absl::FailedPreconditionError(absl::StrCat(
        "parity FAIL for ", feed_date, ": ", differences, " differences"));
  }
  return absl::OkStatus();
}

}  // namespace premarket::ingest
