// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/ingester.h"

#include <cstddef>
#include <memory>
#include <span>
#include <string>
#include <utility>

#include "absl/status/statusor.h"
#include "gtest/gtest.h"
#include "ingest/content_hash.h"
#include "ingest/dedup.h"
#include "ingest/news_item.h"

namespace premarket::ingest {
namespace {

// The same feed as cpp/legacy/tests/ingester_test.cc.
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

std::unique_ptr<FeedProcessor> MakeProcessor(int workers,
                                             std::size_t queue_capacity) {
  absl::StatusOr<std::unique_ptr<FeedProcessor>> processor =
      FeedProcessor::Create({.workers = workers,
                             .queue_capacity = queue_capacity,
                             .max_items = 256,
                             .max_feed_bytes = 1 << 20});
  EXPECT_TRUE(processor.ok()) << processor.status();
  return processor.ok() ? *std::move(processor) : nullptr;
}

TEST(ProcessFeedTest, KeepsFeedOrderAndHashesEveryItem) {
  std::unique_ptr<FeedProcessor> processor = MakeProcessor(4, 8);
  ASSERT_NE(processor, nullptr);
  absl::StatusOr<std::span<NewsItem>> items =
      processor->ProcessFeed(FeedJson(100));
  ASSERT_TRUE(items.ok()) << items.status();
  ASSERT_EQ(items->size(), 100u);
  for (std::size_t i = 0; i < items->size(); ++i) {
    const NewsItem& item = (*items)[i];
    EXPECT_EQ(item.vendor_item_id, "VND-" + std::to_string(i));
    EXPECT_EQ(item.hash(), ContentHash(item.headline, item.body));
    ASSERT_EQ(item.tickers().size(), 1u);
    EXPECT_EQ(item.tickers()[0], "AAPL");
  }
  EXPECT_EQ(processor->ProcessLatencyUs().count, 100u);
  EXPECT_EQ(processor->QueueWaitUs().count, 100u);
}

TEST(ProcessFeedTest, SameResultWithOneOrManyWorkers) {
  std::unique_ptr<FeedProcessor> one = MakeProcessor(1, 1);
  std::unique_ptr<FeedProcessor> many = MakeProcessor(8, 2);
  ASSERT_NE(one, nullptr);
  ASSERT_NE(many, nullptr);
  const std::string feed = FeedJson(50);
  absl::StatusOr<std::span<NewsItem>> a = one->ProcessFeed(feed);
  absl::StatusOr<std::span<NewsItem>> b = many->ProcessFeed(feed);
  ASSERT_TRUE(a.ok());
  ASSERT_TRUE(b.ok());
  for (std::size_t i = 0; i < 50; ++i) {
    EXPECT_EQ((*a)[i].hash(), (*b)[i].hash());
  }
}

TEST(ProcessFeedTest, DuplicatesAreFlaggedNotDropped) {
  std::unique_ptr<FeedProcessor> processor = MakeProcessor(4, 8);
  ASSERT_NE(processor, nullptr);
  absl::StatusOr<std::span<NewsItem>> items =
      processor->ProcessFeed(FeedJson(100));
  ASSERT_TRUE(items.ok());
  HashIndex seen;
  EXPECT_EQ(FlagDuplicates(*items, &seen), 9);  // 10, 20, ..., 90 copy 0
  EXPECT_EQ(items->size(), 100u);
  for (std::size_t i = 0; i < items->size(); ++i) {
    const NewsItem& item = (*items)[i];
    const bool copy = i % 10 == 0 && i > 0;
    EXPECT_EQ(item.is_dup, copy) << "item " << i;
    EXPECT_EQ(item.dup_of, copy ? "VND-0" : "") << "item " << i;
  }
}

TEST(ProcessFeedTest, OneBadItemFailsTheFeed) {
  std::unique_ptr<FeedProcessor> processor = MakeProcessor(2, 2);
  ASSERT_NE(processor, nullptr);
  const std::string feed =
      "{\"items\":[" + ItemJson(0, "ok") + ",{\"id\":\"VND-1\"}]}";
  absl::StatusOr<std::span<NewsItem>> items = processor->ProcessFeed(feed);
  ASSERT_FALSE(items.ok());
  EXPECT_NE(items.status().message().find("#1"), std::string::npos);
}

TEST(ProcessFeedTest, ReportsTheFirstBadItem) {
  std::unique_ptr<FeedProcessor> processor = MakeProcessor(4, 4);
  ASSERT_NE(processor, nullptr);
  std::string feed = "{\"items\":[";
  for (int i = 0; i < 40; ++i) {
    if (i > 0) feed += ",";
    feed += (i == 7 || i == 30) ? "[]" : ItemJson(i, "x");
  }
  absl::StatusOr<std::span<NewsItem>> items =
      processor->ProcessFeed(feed + "]}");
  ASSERT_FALSE(items.ok());
  EXPECT_NE(items.status().message().find("feed item #7:"), std::string::npos)
      << items.status();
}

TEST(ProcessFeedTest, ProcessorIsReusable) {
  std::unique_ptr<FeedProcessor> processor = MakeProcessor(4, 8);
  ASSERT_NE(processor, nullptr);
  for (int round = 0; round < 20; ++round) {
    const int count = 10 + round * 5;
    absl::StatusOr<std::span<NewsItem>> items =
        processor->ProcessFeed(FeedJson(count));
    ASSERT_TRUE(items.ok()) << items.status();
    ASSERT_EQ(items->size(), static_cast<std::size_t>(count));
    EXPECT_EQ((*items)[count - 1].vendor_item_id,
              "VND-" + std::to_string(count - 1));
  }
  EXPECT_FALSE(processor->ProcessFeed("{\"items\":[1]}").ok());
  EXPECT_TRUE(processor->ProcessFeed(FeedJson(3)).ok());
}

TEST(ProcessFeedTest, RejectsFeedsOverTheLimits) {
  std::unique_ptr<FeedProcessor> processor = MakeProcessor(2, 4);
  ASSERT_NE(processor, nullptr);
  EXPECT_FALSE(processor->ProcessFeed(FeedJson(257)).ok());  // > max_items
  EXPECT_FALSE(processor->ProcessFeed(std::string((1 << 20) + 1, ' ')).ok());
}

}  // namespace
}  // namespace premarket::ingest
