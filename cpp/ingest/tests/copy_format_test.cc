// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "db/copy_format.h"

#include <algorithm>
#include <cstddef>
#include <string>
#include <string_view>
#include <vector>

#include "gtest/gtest.h"
#include "ingest/news_item.h"

namespace premarket::ingest {
namespace {

void SetHash(std::string_view hash, NewsItem* item) {
  std::copy(hash.begin(), hash.end(), item->content_hash.begin());
}

// The same expected strings as cpp/legacy/tests/copy_format_test.cc.
TEST(EscapeCopyTextTest, EscapesSpecialCharacters) {
  EXPECT_EQ(EscapeCopyText("a\tb\nc\rd\\e"), "a\\tb\\nc\\rd\\\\e");
  EXPECT_EQ(EscapeCopyText("plain text"), "plain text");
}

TEST(PgTextArrayTest, QuotesElements) {
  std::vector<std::string_view> values;
  EXPECT_EQ(PgTextArray(values), "{}");
  values.push_back("AAPL");
  values.push_back("BRK.B");
  EXPECT_EQ(PgTextArray(values), "{\"AAPL\",\"BRK.B\"}");
  values.push_back("a\"b\\c");
  EXPECT_EQ(PgTextArray(values), "{\"AAPL\",\"BRK.B\",\"a\\\"b\\\\c\"}");
}

TEST(FormatCopyRowTest, ThirteenColumnsAndNewline) {
  NewsItem item;
  item.vendor_item_id = "VND-1";
  item.headline = "Head\tline";
  item.body = "Body\n\nfooter";
  item.source_url = "https://x.example/a";
  item.source_domain = "x.example";
  item.published_at = "2026-09-24T09:05:00Z";
  item.ticker_storage[0] = "AAPL";
  item.ticker_count = 1;
  SetHash("abc", &item);

  const std::string row = FormatCopyRow(42, "2026-09-24", item);
  EXPECT_EQ(row,
            "42\t2026-09-24\tVND-1\tHead\\tline\tBody\\n\\nfooter\t"
            "https://x.example/a\tx.example\t2026-09-24T09:05:00Z\t"
            "{\"AAPL\"}\tt\tabc\tf\t\\N\n");

  item.is_dup = true;
  item.dup_of = "VND-0";
  const std::string dup_row = FormatCopyRow(42, "2026-09-24", item);
  EXPECT_NE(dup_row.find("\tt\tVND-0\n"), std::string::npos);
}

TEST(FormatCopyRowTest, TickersAreArrayThenCopyEscaped) {
  // Legacy writes EscapeCopyText(PgTextArray(tickers)); the one-pass
  // version must produce the same bytes.
  NewsItem item;
  item.ticker_storage[0] = "a\"b\\c";
  item.ticker_storage[1] = "tab\there";
  item.ticker_count = 2;
  const std::string row = FormatCopyRow(1, "d", item);
  const std::string expected = EscapeCopyText(PgTextArray(item.tickers()));
  EXPECT_NE(row.find("\t" + expected + "\t"), std::string::npos) << row;
}

TEST(FormatCopyRowTest, AppendsToOneBuffer) {
  NewsItem item;
  item.vendor_item_id = "A";
  std::string buffer;
  AppendCopyRow(-7, "2026-09-24", item, &buffer);
  AppendCopyRow(9223372036854775807, "2026-09-24", item, &buffer);
  EXPECT_EQ(std::count(buffer.begin(), buffer.end(), '\n'), 2);
  EXPECT_EQ(buffer.find("-7\t"), 0u);
  EXPECT_NE(buffer.find("\n9223372036854775807\t"), std::string::npos);
}

TEST(CopySqlTest, NamesThirteenColumns) {
  const std::string_view sql = kVendorNewsCopySql;
  EXPECT_EQ(std::count(sql.begin(), sql.end(), ','), 12);
  EXPECT_NE(sql.find("ingest.vendor_news_raw"), std::string_view::npos);
}

}  // namespace
}  // namespace premarket::ingest
