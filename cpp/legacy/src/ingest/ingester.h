// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// The `ingest` command: fetch the vendor feed, parse and hash every item on a
// worker pool, flag duplicates and COPY all rows into PostgreSQL.

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_INGEST_INGESTER_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_INGEST_INGESTER_H_

#include <cstddef>
#include <string>
#include <vector>

#include "common/config.h"
#include "common/latency_stats.h"
#include "common/status.h"
#include "ingest/news_item.h"

namespace premarket {
namespace legacy {

// Splits `feed_json` into items, then parses, normalizes and hashes them on
// a ThreadPool of `workers` threads. Returns the items in feed order. Records
// one latency sample per item into `latency` (may be null). Fails if any
// item is malformed.
StatusOr<std::vector<NewsItem>> ProcessFeed(const std::string& feed_json,
                                            int workers,
                                            std::size_t queue_capacity,
                                            LatencyRecorder* latency);

// Runs the whole ingest for `feed_date` and records it in legacy.ingest_run.
Status RunIngest(const Config& config, const std::string& feed_date);

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_INGEST_INGESTER_H_
