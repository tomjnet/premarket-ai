// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/dedup.h"

#include <algorithm>
#include <string_view>
#include <vector>

#include "gtest/gtest.h"
#include "ingest/news_item.h"

namespace premarket::ingest {
namespace {

NewsItem Item(std::string_view id, std::string_view hash) {
  NewsItem item;
  item.vendor_item_id = id;
  std::copy(hash.begin(), hash.end(), item.content_hash.begin());
  return item;
}

// The same cases as cpp/legacy/tests/dedup_test.cc.
TEST(FlagDuplicatesTest, FirstCopyInFeedWins) {
  std::vector<NewsItem> items = {Item("a", "h1"), Item("b", "h2"),
                                 Item("c", "h1"), Item("d", "h1")};
  HashIndex seen;
  EXPECT_EQ(FlagDuplicates(items, &seen), 2);
  EXPECT_FALSE(items[0].is_dup);
  EXPECT_FALSE(items[1].is_dup);
  EXPECT_TRUE(items[2].is_dup);
  EXPECT_EQ(items[2].dup_of, "a");
  EXPECT_EQ(items[3].dup_of, "a");
}

TEST(FlagDuplicatesTest, EarlierFeedsCountAsStaleCopies) {
  HashIndex seen;
  seen["h9"] = "VND-20260921-017";
  std::vector<NewsItem> items = {Item("x", "h9"), Item("y", "h3")};

  EXPECT_EQ(FlagDuplicates(items, &seen), 1);
  EXPECT_TRUE(items[0].is_dup);
  EXPECT_EQ(items[0].dup_of, "VND-20260921-017");
  EXPECT_FALSE(items[1].is_dup);
  EXPECT_TRUE(items[1].dup_of.empty());
}

TEST(FlagDuplicatesTest, EmptyFeed) {
  std::vector<NewsItem> items;
  HashIndex seen;
  EXPECT_EQ(FlagDuplicates(items, &seen), 0);
}

TEST(FlagDuplicatesTest, ResetsFlagsFromAnEarlierRun) {
  std::vector<NewsItem> items = {Item("a", "h1")};
  items[0].is_dup = true;
  items[0].dup_of = "stale";
  HashIndex seen;
  EXPECT_EQ(FlagDuplicates(items, &seen), 0);
  EXPECT_FALSE(items[0].is_dup);
  EXPECT_TRUE(items[0].dup_of.empty());
}

}  // namespace
}  // namespace premarket::ingest
