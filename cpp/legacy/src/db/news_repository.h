// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// All SQL used by the legacy ingest and report commands.

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_DB_NEWS_REPOSITORY_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_DB_NEWS_REPOSITORY_H_

#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "common/latency_stats.h"
#include "common/status.h"
#include "db/pg_connection.h"
#include "ingest/news_item.h"

namespace premarket {
namespace legacy {

struct RunStats {
  int rows_received;
  int rows_inserted;
  int dups;
  LatencySummary latency;
  int64_t total_ms;

  RunStats() : rows_received(0), rows_inserted(0), dups(0), total_ms(0) {}
};

struct RunSummary {
  int64_t run_id;
  std::string finished_et;  // "YYYY-MM-DD HH:MM" America/New_York
  int rows_received;
  int dups;
  int64_t p99_us;

  RunSummary() : run_id(0), rows_received(0), dups(0), p99_us(0) {}
};

struct ReportItem {
  std::string headline;
  std::string body;
  std::string source_domain;
  std::string published_et;  // "HH:MM" America/New_York
  std::string tickers;       // "AAPL, MSFT"
  std::string companies;     // names from legacy.companies, may be empty
};

class NewsRepository {
 public:
  // Does not take ownership of `conn`.
  explicit NewsRepository(PgConnection* conn) : conn_(conn) {}

  // Inserts a RUNNING row into legacy.ingest_run and returns its run_id.
  StatusOr<int64_t> StartRun(const std::string& feed_date, int workers);
  Status FinishRun(int64_t run_id, const RunStats& stats);
  Status FailRun(int64_t run_id, const std::string& error);

  // content_hash -> vendor_item_id of the first copy, for feeds in
  // [feed_date - window_days, feed_date).
  StatusOr<std::map<std::string, std::string>> LoadRecentHashes(
      const std::string& feed_date, int window_days);

  // In one transaction: deletes the rows of `feed_date` (so a re-run is
  // idempotent) and COPYs `items` in.
  Status ReplaceDay(int64_t run_id, const std::string& feed_date,
                    const std::vector<NewsItem>& items);

  // The latest DONE run for `feed_date`; NOT_FOUND if there is none.
  StatusOr<RunSummary> LatestDoneRun(const std::string& feed_date);

  // Non-duplicate items of `feed_date`, newest first.
  StatusOr<std::vector<ReportItem>> LoadReportItems(
      const std::string& feed_date);

 private:
  PgConnection* conn_;
};

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_DB_NEWS_REPOSITORY_H_
