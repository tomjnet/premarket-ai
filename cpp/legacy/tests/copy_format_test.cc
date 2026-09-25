// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "db/copy_format.h"

#include <cstddef>
#include <string>
#include <vector>

#include "gtest/gtest.h"

namespace premarket {
namespace legacy {
namespace {

TEST(EscapeCopyTextTest, EscapesSpecialCharacters) {
  EXPECT_EQ(EscapeCopyText("a\tb\nc\rd\\e"), "a\\tb\\nc\\rd\\\\e");
  EXPECT_EQ(EscapeCopyText("plain text"), "plain text");
}

TEST(PgTextArrayTest, QuotesElements) {
  std::vector<std::string> values;
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
  item.tickers.push_back("AAPL");
  item.content_hash = "abc";

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

TEST(CopySqlTest, NamesThirteenColumns) {
  const std::string sql = kVendorNewsCopySql;
  int commas = 0;
  for (size_t i = 0; i < sql.size(); ++i) {
    if (sql[i] == ',') ++commas;
  }
  EXPECT_EQ(commas, 12);
}

}  // namespace
}  // namespace legacy
}  // namespace premarket
