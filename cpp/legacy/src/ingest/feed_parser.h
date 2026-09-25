// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// RapidJSON parsing of the vendor feed. The main thread splits the feed into
// one JSON string per item; worker threads parse each item on their own.

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_INGEST_FEED_PARSER_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_INGEST_FEED_PARSER_H_

#include <string>
#include <vector>

#include "common/status.h"
#include "ingest/news_item.h"

namespace premarket {
namespace legacy {

// Parses {"feed_date": ..., "items": [ {...}, ... ]} and returns each item
// re-serialized as its own JSON object, in feed order.
StatusOr<std::vector<std::string>> SplitFeed(const std::string& feed_json);

// Parses one item object. Required: id, headline, body, source_url,
// source_domain, published_at (strings) and tickers (array of strings).
// Optional: synthetic (bool, default true).
StatusOr<NewsItem> ParseItem(const std::string& item_json);

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_INGEST_FEED_PARSER_H_
