// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// One vendor news item, as parsed from the feed and stored in
// legacy.vendor_news_raw.

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_INGEST_NEWS_ITEM_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_INGEST_NEWS_ITEM_H_

#include <string>
#include <vector>

namespace premarket {
namespace legacy {

struct NewsItem {
  std::string vendor_item_id;
  std::string headline;
  std::string body;
  std::string source_url;
  std::string source_domain;
  std::string published_at;  // ISO 8601 UTC, e.g. 2026-09-24T09:05:00Z
  std::vector<std::string> tickers;
  bool synthetic;

  // Filled by the ingester.
  std::string content_hash;  // SHA-256 hex of the normalized text
  bool is_dup;
  std::string dup_of;  // vendor_item_id of the first copy, or empty

  NewsItem() : synthetic(true), is_dup(false) {}
};

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_INGEST_NEWS_ITEM_H_
