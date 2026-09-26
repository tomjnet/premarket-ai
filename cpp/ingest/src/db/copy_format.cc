// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "db/copy_format.h"

#include <array>
#include <charconv>
#include <cstdint>
#include <span>
#include <string>
#include <string_view>

namespace premarket::ingest {
namespace {

// COPY escaping of one byte.
void AppendCopyChar(char c, std::string* out) {
  switch (c) {
    case '\\':
      out->append("\\\\");
      break;
    case '\n':
      out->append("\\n");
      break;
    case '\r':
      out->append("\\r");
      break;
    case '\t':
      out->append("\\t");
      break;
    default:
      out->push_back(c);
  }
}

// Appends the text[] literal of `values`, array-escaped and then
// COPY-escaped in one pass (legacy: EscapeCopyText(PgTextArray(values))).
// Only '\\' needs both: array level doubles it, COPY level doubles each.
void AppendCopyTextArray(std::span<const std::string_view> values,
                         std::string* out) {
  out->push_back('{');
  bool first = true;
  for (const std::string_view value : values) {
    if (!first) out->push_back(',');
    first = false;
    out->push_back('"');
    for (const char c : value) {
      if (c == '"' || c == '\\') AppendCopyChar('\\', out);
      AppendCopyChar(c, out);
    }
    out->push_back('"');
  }
  out->push_back('}');
}

void AppendInt(int64_t value, std::string* out) {
  std::array<char, 24> digits{};
  const std::to_chars_result result =
      std::to_chars(digits.data(), digits.data() + digits.size(), value);
  out->append(digits.data(), result.ptr);
}

}  // namespace

void AppendCopyText(std::string_view value, std::string* out) {
  for (const char c : value) AppendCopyChar(c, out);
}

std::string EscapeCopyText(std::string_view value) {
  std::string out;
  out.reserve(value.size() + 8);
  AppendCopyText(value, &out);
  return out;
}

std::string PgTextArray(std::span<const std::string_view> values) {
  std::string out = "{";
  bool first = true;
  for (const std::string_view value : values) {
    if (!first) out.push_back(',');
    first = false;
    out.push_back('"');
    for (const char c : value) {
      if (c == '"' || c == '\\') out.push_back('\\');
      out.push_back(c);
    }
    out.push_back('"');
  }
  out.push_back('}');
  return out;
}

void AppendCopyRow(int64_t run_id, std::string_view feed_date,
                   const NewsItem& item, std::string* out) {
  AppendInt(run_id, out);
  out->push_back('\t');
  AppendCopyText(feed_date, out);
  out->push_back('\t');
  AppendCopyText(item.vendor_item_id, out);
  out->push_back('\t');
  AppendCopyText(item.headline, out);
  out->push_back('\t');
  AppendCopyText(item.body, out);
  out->push_back('\t');
  AppendCopyText(item.source_url, out);
  out->push_back('\t');
  AppendCopyText(item.source_domain, out);
  out->push_back('\t');
  AppendCopyText(item.published_at, out);
  out->push_back('\t');
  AppendCopyTextArray(item.tickers(), out);
  out->push_back('\t');
  out->push_back(item.synthetic ? 't' : 'f');
  out->push_back('\t');
  AppendCopyText(item.hash(), out);
  out->push_back('\t');
  out->push_back(item.is_dup ? 't' : 'f');
  out->push_back('\t');
  if (item.dup_of.empty()) {
    out->append("\\N");
  } else {
    AppendCopyText(item.dup_of, out);
  }
  out->push_back('\n');
}

std::string FormatCopyRow(int64_t run_id, std::string_view feed_date,
                          const NewsItem& item) {
  std::string row;
  row.reserve(item.headline.size() + item.body.size() + 256);
  AppendCopyRow(run_id, feed_date, item, &row);
  return row;
}

}  // namespace premarket::ingest
