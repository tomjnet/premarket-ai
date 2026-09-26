// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Builds rows for PostgreSQL COPY ... FROM STDIN (text format). The bytes
// are the same as legacy's copy_format.cc, so both schemas store identical
// values; rows are appended to one reusable buffer instead of one string
// per row.

#ifndef PREMARKET_AI_CPP_INGEST_SRC_DB_COPY_FORMAT_H_
#define PREMARKET_AI_CPP_INGEST_SRC_DB_COPY_FORMAT_H_

#include <cstdint>
#include <span>
#include <string>
#include <string_view>

#include "ingest/news_item.h"

namespace premarket::ingest {

// The column list matching AppendCopyRow().
inline constexpr std::string_view kVendorNewsCopySql =
    "COPY ingest.vendor_news_raw (run_id, feed_date, vendor_item_id, "
    "headline, body, source_url, source_domain, published_at, tickers, "
    "synthetic, content_hash, is_dup, dup_of) FROM STDIN";

// Appends `value` with backslash, newline, carriage return and tab escaped
// for COPY text format.
void AppendCopyText(std::string_view value, std::string* out);
std::string EscapeCopyText(std::string_view value);

// PostgreSQL text[] literal: {"AAPL","MSFT"} with quotes and backslashes
// escaped inside elements. Not COPY-escaped yet.
std::string PgTextArray(std::span<const std::string_view> values);

// Appends one tab-separated, newline-terminated COPY row for
// ingest.vendor_news_raw. Allocates only if `out` has to grow.
void AppendCopyRow(int64_t run_id, std::string_view feed_date,
                   const NewsItem& item, std::string* out);
std::string FormatCopyRow(int64_t run_id, std::string_view feed_date,
                          const NewsItem& item);

}  // namespace premarket::ingest

#endif  // PREMARKET_AI_CPP_INGEST_SRC_DB_COPY_FORMAT_H_
