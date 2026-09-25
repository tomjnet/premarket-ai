// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "db/copy_format.h"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace premarket {
namespace legacy {

const char kVendorNewsCopySql[] =
    "COPY legacy.vendor_news_raw (run_id, feed_date, vendor_item_id, "
    "headline, body, source_url, source_domain, published_at, tickers, "
    "synthetic, content_hash, is_dup, dup_of) FROM STDIN";

std::string EscapeCopyText(const std::string& value) {
  std::string out;
  out.reserve(value.size() + 8);
  for (std::size_t i = 0; i < value.size(); ++i) {
    const char c = value[i];
    switch (c) {
      case '\\':
        out += "\\\\";
        break;
      case '\n':
        out += "\\n";
        break;
      case '\r':
        out += "\\r";
        break;
      case '\t':
        out += "\\t";
        break;
      default:
        out.push_back(c);
    }
  }
  return out;
}

std::string PgTextArray(const std::vector<std::string>& values) {
  std::string out = "{";
  for (std::size_t i = 0; i < values.size(); ++i) {
    if (i > 0) out.push_back(',');
    out.push_back('"');
    for (std::size_t j = 0; j < values[i].size(); ++j) {
      const char c = values[i][j];
      if (c == '"' || c == '\\') out.push_back('\\');
      out.push_back(c);
    }
    out.push_back('"');
  }
  out.push_back('}');
  return out;
}

std::string FormatCopyRow(int64_t run_id, const std::string& feed_date,
                          const NewsItem& item) {
  std::string row;
  row.reserve(item.headline.size() + item.body.size() + 256);
  row += std::to_string(run_id);
  row += '\t';
  row += EscapeCopyText(feed_date);
  row += '\t';
  row += EscapeCopyText(item.vendor_item_id);
  row += '\t';
  row += EscapeCopyText(item.headline);
  row += '\t';
  row += EscapeCopyText(item.body);
  row += '\t';
  row += EscapeCopyText(item.source_url);
  row += '\t';
  row += EscapeCopyText(item.source_domain);
  row += '\t';
  row += EscapeCopyText(item.published_at);
  row += '\t';
  row += EscapeCopyText(PgTextArray(item.tickers));
  row += '\t';
  row += item.synthetic ? "t" : "f";
  row += '\t';
  row += EscapeCopyText(item.content_hash);
  row += '\t';
  row += item.is_dup ? "t" : "f";
  row += '\t';
  row += item.dup_of.empty() ? "\\N" : EscapeCopyText(item.dup_of);
  row += '\n';
  return row;
}

}  // namespace legacy
}  // namespace premarket
