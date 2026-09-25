// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/ingester.h"

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "common/logging.h"
#include "db/news_repository.h"
#include "db/pg_connection.h"
#include "ingest/dedup.h"
#include "ingest/feed_client.h"
#include "ingest/feed_parser.h"
#include "ingest/normalize.h"
#include "ingest/thread_pool.h"

namespace premarket {
namespace legacy {
namespace {

typedef std::chrono::steady_clock Clock;

int64_t MicrosSince(Clock::time_point start) {
  return std::chrono::duration_cast<std::chrono::microseconds>(Clock::now() -
                                                               start)
      .count();
}

// Parses, normalizes and hashes one item. Runs on a worker thread; each call
// writes only its own slot of `items` / `statuses`.
void ProcessOne(const std::string* item_json, NewsItem* item, Status* status,
                LatencyRecorder* latency) {
  const Clock::time_point start = Clock::now();
  StatusOr<NewsItem> parsed = ParseItem(*item_json);
  if (!parsed.ok()) {
    *status = parsed.status();
    return;
  }
  *item = parsed.value();
  item->content_hash = ContentHash(item->headline, item->body);
  if (latency != nullptr) latency->Record(MicrosSince(start));
}

Status ItemError(std::size_t index, const Status& status) {
  return InvalidArgumentError("feed item #" + std::to_string(index) + ": " +
                              status.message());
}

// Everything after the run row exists; any error marks the run FAILED.
Status IngestIntoRun(const Config& config, const std::string& feed_date,
                     int64_t run_id, NewsRepository* repo) {
  const Clock::time_point start = Clock::now();
  const std::string url = FeedUrlForDate(config.feed_url, feed_date);
  LogInfo("fetching " + url);
  StatusOr<std::string> feed = FetchUrl(url, config.fetch_retries);
  if (!feed.ok()) return feed.status();

  LatencyRecorder latency;
  StatusOr<std::vector<NewsItem>> processed = ProcessFeed(
      feed.value(), config.workers, config.queue_capacity, &latency);
  if (!processed.ok()) return processed.status();
  std::vector<NewsItem>* items = processed.mutable_value();

  StatusOr<std::map<std::string, std::string>> known =
      repo->LoadRecentHashes(feed_date, config.dedup_window_days);
  if (!known.ok()) return known.status();
  const int dups = FlagDuplicates(known.value(), items);

  Status status = repo->ReplaceDay(run_id, feed_date, *items);
  if (!status.ok()) return status;

  RunStats stats;
  stats.rows_received = static_cast<int>(items->size());
  stats.rows_inserted = static_cast<int>(items->size());
  stats.dups = dups;
  stats.latency = latency.Summarize();
  stats.total_ms = MicrosSince(start) / 1000;
  status = repo->FinishRun(run_id, stats);
  if (!status.ok()) return status;

  LogInfo("run " + std::to_string(run_id) +
          " DONE: " + std::to_string(stats.rows_received) + " received, " +
          std::to_string(stats.rows_inserted) + " inserted, " +
          std::to_string(dups) + " duplicates flagged, p50/p99/p99.9 = " +
          std::to_string(stats.latency.p50_us) + "/" +
          std::to_string(stats.latency.p99_us) + "/" +
          std::to_string(stats.latency.p999_us) + " us, total " +
          std::to_string(stats.total_ms) + " ms");
  return OkStatus();
}

}  // namespace

StatusOr<std::vector<NewsItem>> ProcessFeed(const std::string& feed_json,
                                            int workers,
                                            std::size_t queue_capacity,
                                            LatencyRecorder* latency) {
  StatusOr<std::vector<std::string>> split = SplitFeed(feed_json);
  if (!split.ok()) return split.status();
  const std::vector<std::string>& raw = split.value();

  std::vector<NewsItem> items(raw.size());
  std::vector<Status> statuses(raw.size());
  {
    ThreadPool pool(workers, queue_capacity);
    for (std::size_t i = 0; i < raw.size(); ++i) {
      const std::string* item_json = &raw[i];
      NewsItem* item = &items[i];
      Status* status = &statuses[i];
      pool.Submit([item_json, item, status, latency]() {
        ProcessOne(item_json, item, status, latency);
      });
    }
    pool.Shutdown();  // waits for every task
  }

  for (std::size_t i = 0; i < statuses.size(); ++i) {
    if (!statuses[i].ok()) {
      return ItemError(i, statuses[i]);
    }
  }
  return items;
}

Status RunIngest(const Config& config, const std::string& feed_date) {
  std::unique_ptr<PgConnection> conn;
  Status status = PgConnection::Connect(config.pg_conninfo, &conn);
  if (!status.ok()) return status;
  NewsRepository repo(conn.get());

  StatusOr<int64_t> run_id = repo.StartRun(feed_date, config.workers);
  if (!run_id.ok()) return run_id.status();
  LogInfo("ingest run " + std::to_string(run_id.value()) + " started for " +
          feed_date + " with " + std::to_string(config.workers) + " workers");

  status = IngestIntoRun(config, feed_date, run_id.value(), &repo);
  if (!status.ok()) {
    Status failed = repo.FailRun(run_id.value(), status.ToString());
    if (!failed.ok()) {
      LogError("could not mark run FAILED: " + failed.message());
    }
  }
  return status;
}

}  // namespace legacy
}  // namespace premarket
