// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// The `ingest` command: fetch the vendor feed, parse it once, extract and
// hash every item on the lock-free worker pool, flag duplicates and COPY all
// rows into ingest.vendor_news_raw.
//
// FeedProcessor owns everything a run needs, allocated once at startup from
// the config: the feed buffer, the JSON parser, the item array, per-worker
// hashers and latency samples, and the worker pool. Processing a feed then
// allocates nothing.

#ifndef PREMARKET_AI_CPP_INGEST_SRC_INGEST_INGESTER_H_
#define PREMARKET_AI_CPP_INGEST_SRC_INGEST_INGESTER_H_

#include <cstddef>
#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "common/config.h"
#include "common/latency.h"
#include "ingest/content_hash.h"
#include "ingest/feed_parser.h"
#include "ingest/news_item.h"
#include "ingest/worker_pool.h"

namespace premarket::ingest {

struct ProcessorOptions {
  int workers = 4;
  std::size_t queue_capacity = 64;
  std::size_t max_items = 4096;
  std::size_t max_feed_bytes = std::size_t{64} << 20;
  bool pin_cpus = false;
};

class FeedProcessor {
 public:
  static absl::StatusOr<std::unique_ptr<FeedProcessor>> Create(
      const ProcessorOptions& options);

  FeedProcessor(const FeedProcessor&) = delete;
  FeedProcessor& operator=(const FeedProcessor&) = delete;

  // The buffer FetchUrl() writes the raw feed into.
  FeedBuffer* buffer() { return &buffer_; }

  // Copies `feed_json` into the buffer, then ProcessBuffered(). For tests
  // and benchmarks.
  absl::StatusOr<std::span<NewsItem>> ProcessFeed(std::string_view feed_json);

  // Parses the buffer, then extracts, validates and hashes every item on
  // the worker pool. Returns the items in feed order, valid until the next
  // call. Fails if any item is malformed ("feed item #<i>: ...", the
  // lowest index, like legacy).
  absl::StatusOr<std::span<NewsItem>> ProcessBuffered();

  // Of the last call, in microseconds: per-item processing time and queue
  // wait, whole-feed parse and pool time.
  LatencySummary ProcessLatencyUs();
  LatencySummary QueueWaitUs();
  int64_t parse_us() const { return parse_us_; }
  int64_t pool_us() const { return pool_us_; }
  int workers() const { return pool_.size(); }

 private:
  // Per-worker state, each on its own cache lines.
  struct alignas(kCacheLineSize) WorkerScratch {
    std::unique_ptr<ContentHasher> hasher;
    SampleBuffer process_ns;
  };

  FeedProcessor(const ProcessorOptions& options,
                std::unique_ptr<FeedParser> parser,
                std::vector<std::unique_ptr<ContentHasher>> hashers);

  // Runs on worker `worker`; writes only items_[index] and its own scratch.
  void ProcessOne(std::uint32_t index, int worker);

  FeedBuffer buffer_;
  std::unique_ptr<FeedParser> parser_;
  std::vector<NewsItem> items_;
  std::vector<WorkerScratch> scratch_;
  std::vector<const SampleBuffer*> process_views_;
  LatencyMerger merger_;
  int64_t parse_us_ = 0;
  int64_t pool_us_ = 0;
  // Last member: its workers stop before the state above goes away.
  WorkerPool pool_;
};

// Runs the whole ingest for `feed_date` and records it in
// ingest.ingest_run.
absl::Status RunIngest(const Config& config, const std::string& feed_date);

}  // namespace premarket::ingest

#endif  // PREMARKET_AI_CPP_INGEST_SRC_INGEST_INGESTER_H_
