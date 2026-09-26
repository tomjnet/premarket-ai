// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "common/latency.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <thread>
#include <vector>

#include "gtest/gtest.h"

namespace premarket::ingest {
namespace {

// The same cases as cpp/legacy/tests/latency_stats_test.cc.
TEST(PercentileTest, NearestRank) {
  std::vector<int64_t> sorted;
  for (int64_t i = 1; i <= 1000; ++i) sorted.push_back(i);
  EXPECT_EQ(Percentile(sorted, 0.50), 500);
  EXPECT_EQ(Percentile(sorted, 0.99), 990);
  EXPECT_EQ(Percentile(sorted, 0.999), 999);
  EXPECT_EQ(Percentile(sorted, 1.0), 1000);
}

TEST(PercentileTest, SmallAndEmpty) {
  EXPECT_EQ(Percentile(std::vector<int64_t>(), 0.5), 0);
  EXPECT_EQ(Percentile(std::vector<int64_t>(1, 7), 0.999), 7);
}

TEST(SummarizeTest, SortsAndSummarizes) {
  std::vector<int64_t> samples = {5, 1, 4, 2, 3};
  const LatencySummary summary = Summarize(samples);
  EXPECT_EQ(summary.count, 5u);
  EXPECT_EQ(summary.p50, 3);
  EXPECT_EQ(summary.p99, 5);
  EXPECT_EQ(summary.max, 5);
}

TEST(SampleBufferTest, FixedCapacityCountsDropped) {
  SampleBuffer buffer(2);
  buffer.Record(1);
  buffer.Record(2);
  buffer.Record(3);
  EXPECT_EQ(buffer.samples().size(), 2u);
  EXPECT_EQ(buffer.dropped(), 1u);
  buffer.Clear();
  EXPECT_TRUE(buffer.samples().empty());
  EXPECT_EQ(buffer.dropped(), 0u);
}

TEST(LatencyMergerTest, MergesPerThreadBuffers) {
  // Four threads, each with its own buffer, like the worker pool.
  std::vector<SampleBuffer> buffers(4, SampleBuffer(250));
  std::vector<std::thread> threads;
  for (int t = 0; t < 4; ++t) {
    threads.emplace_back([&buffers, t] {
      for (int i = 0; i < 250; ++i) {
        buffers[static_cast<std::size_t>(t)].Record((t * 250 + i + 1) * 1000);
      }
    });
  }
  for (std::thread& thread : threads) thread.join();

  const std::array<const SampleBuffer*, 4> views = {&buffers[0], &buffers[1],
                                                    &buffers[2], &buffers[3]};
  LatencyMerger merger(1000);
  const LatencySummary summary = merger.Summarize(views, 1000);
  EXPECT_EQ(summary.count, 1000u);
  EXPECT_EQ(summary.p50, 500);
  EXPECT_EQ(summary.p99, 990);
  EXPECT_EQ(summary.max, 1000);
}

TEST(LatencyMergerTest, EmptySummaryIsZero) {
  LatencyMerger merger(4);
  const LatencySummary summary = merger.Summarize({}, 1);
  EXPECT_EQ(summary.count, 0u);
  EXPECT_EQ(summary.p99, 0);
}

}  // namespace
}  // namespace premarket::ingest
