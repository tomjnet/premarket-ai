// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Builds rows for PostgreSQL COPY ... FROM STDIN (text format).

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_DB_COPY_FORMAT_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_DB_COPY_FORMAT_H_

#include <cstdint>
#include <string>
#include <vector>

#include "ingest/news_item.h"

namespace premarket {
namespace legacy {

// The column list matching FormatCopyRow().
extern const char kVendorNewsCopySql[];

// Escapes backslash, newline, carriage return and tab for COPY text format.
std::string EscapeCopyText(const std::string& value);

// PostgreSQL text[] literal: {"AAPL","MSFT"} with quotes and backslashes
// escaped inside elements. Not COPY-escaped yet.
std::string PgTextArray(const std::vector<std::string>& values);

// One tab-separated, newline-terminated COPY row for legacy.vendor_news_raw.
std::string FormatCopyRow(int64_t run_id, const std::string& feed_date,
                          const NewsItem& item);

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_DB_COPY_FORMAT_H_
