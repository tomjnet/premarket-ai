// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/dedup.h"

#include <map>
#include <string>
#include <vector>

#include "gtest/gtest.h"

namespace premarket {
namespace legacy {
namespace {

NewsItem Item(const std::string& id, const std::string& hash) {
  NewsItem item;
  item.vendor_item_id = id;
  item.content_hash = hash;
  return item;
}

TEST(FlagDuplicatesTest, FirstCopyInFeedWins) {
  std::vector<NewsItem> items;
  items.push_back(Item("a", "h1"));
  items.push_back(Item("b", "h2"));
  items.push_back(Item("c", "h1"));
  items.push_back(Item("d", "h1"));

  EXPECT_EQ(FlagDuplicates(std::map<std::string, std::string>(), &items), 2);
  EXPECT_FALSE(items[0].is_dup);
  EXPECT_FALSE(items[1].is_dup);
  EXPECT_TRUE(items[2].is_dup);
  EXPECT_EQ(items[2].dup_of, "a");
  EXPECT_EQ(items[3].dup_of, "a");
}

TEST(FlagDuplicatesTest, EarlierFeedsCountAsStaleCopies) {
  std::map<std::string, std::string> known;
  known["h9"] = "VND-20260921-017";
  std::vector<NewsItem> items;
  items.push_back(Item("x", "h9"));
  items.push_back(Item("y", "h3"));

  EXPECT_EQ(FlagDuplicates(known, &items), 1);
  EXPECT_TRUE(items[0].is_dup);
  EXPECT_EQ(items[0].dup_of, "VND-20260921-017");
  EXPECT_FALSE(items[1].is_dup);
  EXPECT_TRUE(items[1].dup_of.empty());
}

TEST(FlagDuplicatesTest, EmptyFeed) {
  std::vector<NewsItem> items;
  EXPECT_EQ(FlagDuplicates(std::map<std::string, std::string>(), &items), 0);
}

}  // namespace
}  // namespace legacy
}  // namespace premarket
