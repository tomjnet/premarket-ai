// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// The SQL used by the `ingest` command, against the ingest.* schema.

#ifndef PREMARKET_AI_CPP_INGEST_SRC_DB_REPOSITORY_H_
#define PREMARKET_AI_CPP_INGEST_SRC_DB_REPOSITORY_H_

#include <cstdint>
#include <span>
#include <string>

#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "common/latency.h"
#include "db/pg_connection.h"
#include "ingest/dedup.h"
#include "ingest/news_item.h"

namespace premarket::ingest {

// What ingest.ingest_run records for a DONE run.
struct RunStats {
  int rows_received = 0;
  int rows_inserted = 0;
  int dups = 0;
  LatencySummary process_us;  // per item: extract + validate + hash
  LatencySummary wait_us;     // per item: queue enqueue -> dequeue
  int64_t fetch_ms = 0;
  int64_t parse_us = 0;
  int64_t dedup_us = 0;
  int64_t copy_ms = 0;
  int64_t total_ms = 0;
};

// Runs the SQL file at `path` (the idempotent ingest schema) in one
// transaction, serialized by an advisory lock so concurrent runs cannot
// race on CREATE ... IF NOT EXISTS.
absl::Status ApplySchemaFile(const std::string& path, PgConnection* conn);

class Repository {
 public:
  // Does not take ownership of `conn`.
  explicit Repository(PgConnection* conn) : conn_(conn) {}

  // Inserts a RUNNING row into ingest.ingest_run and returns its run_id.
  absl::StatusOr<int64_t> StartRun(const std::string& feed_date, int workers);
  absl::Status FinishRun(int64_t run_id, const RunStats& stats);
  absl::Status FailRun(int64_t run_id, const std::string& error);

  // Adds content_hash -> vendor_item_id of the first copy, for feeds in
  // [feed_date - window_days, feed_date), to `seen`. The views point into
  // `storage`, which must outlive them. Same query as legacy.
  absl::Status LoadRecentHashes(const std::string& feed_date, int window_days,
                                PgResult* storage, HashIndex* seen);

  // In one transaction: deletes the rows of `feed_date` (so a re-run is
  // idempotent) and COPYs `items` in. `buffer` is reused for the COPY text.
  absl::Status ReplaceDay(int64_t run_id, const std::string& feed_date,
                          std::span<const NewsItem> items, std::string* buffer);

 private:
  PgConnection* conn_;
};

}  // namespace premarket::ingest

#endif  // PREMARKET_AI_CPP_INGEST_SRC_DB_REPOSITORY_H_
