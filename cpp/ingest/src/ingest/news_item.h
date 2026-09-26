// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// One vendor news item, as parsed from the feed and stored in
// ingest.vendor_news_raw. Every text field is a view into memory that lives
// for the whole run (the simdjson parser's string buffer, or a PostgreSQL
// result for dup_of), so filling an item never allocates.

#ifndef PREMARKET_AI_CPP_INGEST_SRC_INGEST_NEWS_ITEM_H_
#define PREMARKET_AI_CPP_INGEST_SRC_INGEST_NEWS_ITEM_H_

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>

#include "ingest/mpmc_queue.h"

namespace premarket::ingest {

// More tickers than this fails the item (the vendor sends one or two).
inline constexpr std::size_t kMaxTickers = 8;

// Hex SHA-256 plus a terminating NUL.
inline constexpr std::size_t kContentHashSize = 65;

// Why an item was rejected. The message is built on the main thread after
// the run, so workers never allocate for errors.
enum class ItemError : std::uint8_t {
  kNone,
  kNotObject,         // item must be a JSON object
  kMissingField,      // missing field '<field>'
  kNotString,         // field '<field>' is not a string
  kEmptyId,           // field 'id' is empty
  kTickersNotArray,   // 'tickers' must be an array
  kTickerNotString,   // ticker is not a string
  kTooManyTickers,    // more than kMaxTickers tickers
  kSyntheticNotBool,  // 'synthetic' must be a boolean
  kHashFailed,        // OpenSSL failed to hash the item
};

// One cache line multiple, so workers filling neighbouring items do not
// false-share.
struct alignas(kCacheLineSize) NewsItem {
  std::string_view vendor_item_id;
  std::string_view headline;
  std::string_view body;
  std::string_view source_url;
  std::string_view source_domain;
  std::string_view published_at;  // ISO 8601 UTC, e.g. 2026-09-24T09:05:00Z
  std::array<std::string_view, kMaxTickers> ticker_storage{};
  std::uint8_t ticker_count = 0;
  bool synthetic = true;

  // Filled by the ingester.
  bool is_dup = false;
  ItemError error = ItemError::kNone;
  const char* error_field = "";  // static string naming the bad field
  std::string_view dup_of;       // vendor_item_id of the first copy
  std::array<char, kContentHashSize> content_hash{};  // NUL-terminated

  std::span<const std::string_view> tickers() const {
    return {ticker_storage.data(), ticker_count};
  }
  // content_hash up to its NUL (64 hex digits once hashed).
  std::string_view hash() const { return {content_hash.data()}; }
};

}  // namespace premarket::ingest

#endif  // PREMARKET_AI_CPP_INGEST_SRC_INGEST_NEWS_ITEM_H_
