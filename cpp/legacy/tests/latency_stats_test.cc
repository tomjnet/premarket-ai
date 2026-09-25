// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "common/latency_stats.h"

#include <cstddef>
#include <cstdint>
#include <thread>
#include <vector>

#include "gtest/gtest.h"

namespace premarket {
namespace legacy {
namespace {

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

TEST(LatencyRecorderTest, SummarizesFromManyThreads) {
  LatencyRecorder recorder;
  std::vector<std::thread> threads;
  for (int t = 0; t < 4; ++t) {
    threads.push_back(std::thread([&recorder, t]() {
      for (int i = 0; i < 250; ++i) recorder.Record(t * 250 + i + 1);
    }));
  }
  for (size_t i = 0; i < threads.size(); ++i) threads[i].join();

  const LatencySummary summary = recorder.Summarize();
  EXPECT_EQ(summary.count, 1000u);
  EXPECT_EQ(summary.p50_us, 500);
  EXPECT_EQ(summary.p99_us, 990);
  EXPECT_EQ(summary.max_us, 1000);
}

TEST(LatencyRecorderTest, EmptySummaryIsZero) {
  LatencyRecorder recorder;
  const LatencySummary summary = recorder.Summarize();
  EXPECT_EQ(summary.count, 0u);
  EXPECT_EQ(summary.p99_us, 0);
}

}  // namespace
}  // namespace legacy
}  // namespace premarket
