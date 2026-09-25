// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/ingester.h"

#include <cstddef>
#include <map>
#include <string>
#include <vector>

#include "common/latency_stats.h"
#include "gtest/gtest.h"
#include "ingest/dedup.h"
#include "ingest/normalize.h"

namespace premarket {
namespace legacy {
namespace {

std::string ItemJson(int n, const std::string& headline) {
  return "{\"id\":\"VND-" + std::to_string(n) + "\",\"headline\":\"" +
         headline +
         "\",\"body\":\"Body text.\",\"source_url\":\"https://a.example/" +
         std::to_string(n) +
         "\",\"source_domain\":\"a.example\","
         "\"published_at\":\"2026-09-24T09:00:00Z\",\"tickers\":[\"AAPL\"]}";
}

// `count` items; every 10th repeats item 0's text in upper case.
std::string FeedJson(int count) {
  std::string feed = "{\"feed_date\":\"2026-09-24\",\"items\":[";
  for (int i = 0; i < count; ++i) {
    if (i > 0) feed += ",";
    const std::string headline =
        (i % 10 == 0 && i > 0) ? "STORY 0" : "Story " + std::to_string(i);
    feed += ItemJson(i, headline);
  }
  return feed + "]}";
}

TEST(ProcessFeedTest, KeepsFeedOrderAndHashesEveryItem) {
  LatencyRecorder latency;
  StatusOr<std::vector<NewsItem>> items =
      ProcessFeed(FeedJson(100), 4, 8, &latency);
  ASSERT_TRUE(items.ok()) << items.status().ToString();
  ASSERT_EQ(items.value().size(), 100u);
  for (size_t i = 0; i < items.value().size(); ++i) {
    const NewsItem& item = items.value()[i];
    EXPECT_EQ(item.vendor_item_id, "VND-" + std::to_string(i));
    EXPECT_EQ(item.content_hash, ContentHash(item.headline, item.body));
  }
  EXPECT_EQ(latency.Summarize().count, 100u);
}

TEST(ProcessFeedTest, SameResultWithOneOrManyWorkers) {
  StatusOr<std::vector<NewsItem>> one =
      ProcessFeed(FeedJson(50), 1, 1, nullptr);
  StatusOr<std::vector<NewsItem>> many =
      ProcessFeed(FeedJson(50), 8, 2, nullptr);
  ASSERT_TRUE(one.ok());
  ASSERT_TRUE(many.ok());
  for (size_t i = 0; i < 50; ++i) {
    EXPECT_EQ(one.value()[i].content_hash, many.value()[i].content_hash);
  }
}

TEST(ProcessFeedTest, DuplicatesAreFlaggedNotDropped) {
  StatusOr<std::vector<NewsItem>> items =
      ProcessFeed(FeedJson(100), 4, 8, nullptr);
  ASSERT_TRUE(items.ok());
  const int dups = FlagDuplicates(std::map<std::string, std::string>(),
                                  items.mutable_value());
  EXPECT_EQ(dups, 9);  // items 10, 20, ..., 90 copy item 0
  EXPECT_EQ(items.value().size(), 100u);
  EXPECT_TRUE(items.value()[10].is_dup);
  EXPECT_EQ(items.value()[10].dup_of, "VND-0");
}

TEST(ProcessFeedTest, OneBadItemFailsTheFeed) {
  const std::string feed =
      "{\"items\":[" + ItemJson(0, "ok") + ",{\"id\":\"VND-1\"}]}";
  StatusOr<std::vector<NewsItem>> items = ProcessFeed(feed, 2, 2, nullptr);
  ASSERT_FALSE(items.ok());
  EXPECT_NE(items.status().message().find("#1"), std::string::npos);
}

}  // namespace
}  // namespace legacy
}  // namespace premarket
