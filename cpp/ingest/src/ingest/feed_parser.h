// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// simdjson parsing of the vendor feed (DOM API, error codes, no
// exceptions). The main thread parses the whole feed once and collects one
// element handle per item; worker threads then read their items from the
// parsed document concurrently (read only) and extract the fields as views.
// Legacy re-serializes every item and parses it again on a worker.

#ifndef PREMARKET_AI_CPP_INGEST_SRC_INGEST_FEED_PARSER_H_
#define PREMARKET_AI_CPP_INGEST_SRC_INGEST_FEED_PARSER_H_

#include <simdjson.h>

#include <cstddef>
#include <memory>
#include <string_view>
#include <vector>

#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "ingest/news_item.h"

namespace premarket::ingest {

// Fixed-capacity byte buffer for the raw feed, with the zero-copy padding
// simdjson needs after the last byte. Allocated once.
class FeedBuffer {
 public:
  explicit FeedBuffer(std::size_t capacity);

  // False (and nothing copied) when the bytes would exceed the capacity.
  bool Append(const char* bytes, std::size_t count);
  bool Assign(std::string_view bytes) {
    Clear();
    return Append(bytes.data(), bytes.size());
  }
  void Clear();

  const char* data() const { return data_.get(); }
  std::size_t size() const { return size_; }
  std::size_t capacity() const { return capacity_; }
  std::string_view view() const { return {data_.get(), size_}; }

 private:
  void ZeroPadding();

  const std::size_t capacity_;
  std::size_t size_ = 0;
  // capacity_ + SIMDJSON_PADDING bytes, deliberately not zero-filled.
  std::unique_ptr<char[]> data_;  // NOLINT(modernize-avoid-c-arrays)
};

class FeedParser {
 public:
  // Allocates the parser for feeds of up to `max_feed_bytes` and the item
  // handle array for up to `max_items` items.
  static absl::StatusOr<std::unique_ptr<FeedParser>> Create(
      std::size_t max_feed_bytes, std::size_t max_items);

  FeedParser(const FeedParser&) = delete;
  FeedParser& operator=(const FeedParser&) = delete;

  // Main thread. Parses {"feed_date": ..., "items": [ {...}, ... ]} and
  // collects the items in feed order. Invalidates earlier results.
  absl::Status Parse(const FeedBuffer& feed);

  std::size_t item_count() const { return items_.size(); }

  // Any thread, concurrently. Fills `item` from item `index`. Required:
  // id, headline, body, source_url, source_domain, published_at (strings)
  // and tickers (array of strings). Optional: synthetic (bool, default
  // true). On failure sets item->error / error_field and returns false.
  // Views stay valid until the next Parse(). No allocation.
  bool ExtractItem(std::size_t index, NewsItem* item) const;

 private:
  explicit FeedParser(std::size_t max_items) : max_items_(max_items) {}

  const std::size_t max_items_;
  simdjson::dom::parser parser_;
  std::vector<simdjson::dom::element> items_;
};

// The error of a failed item, worded like legacy's ParseItem().
absl::Status ItemErrorStatus(const NewsItem& item);

}  // namespace premarket::ingest

#endif  // PREMARKET_AI_CPP_INGEST_SRC_INGEST_FEED_PARSER_H_
