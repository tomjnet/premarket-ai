// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Collects per-item latencies (microseconds) from many threads and reports
// p50 / p99 / p99.9. Classic design: a mutex around a growing vector.

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_COMMON_LATENCY_STATS_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_COMMON_LATENCY_STATS_H_

#include <cstddef>
#include <cstdint>
#include <mutex>
#include <vector>

namespace premarket {
namespace legacy {

struct LatencySummary {
  std::size_t count;
  int64_t p50_us;
  int64_t p99_us;
  int64_t p999_us;
  int64_t max_us;

  LatencySummary() : count(0), p50_us(0), p99_us(0), p999_us(0), max_us(0) {}
};

// Nearest-rank percentile of an ascending-sorted vector; 0 when empty.
// `fraction` is in (0, 1], for example 0.99.
int64_t Percentile(const std::vector<int64_t>& sorted, double fraction);

class LatencyRecorder {
 public:
  LatencyRecorder() {}
  LatencyRecorder(const LatencyRecorder&) = delete;
  LatencyRecorder& operator=(const LatencyRecorder&) = delete;

  // Thread safe.
  void Record(int64_t micros);

  // Thread safe. Sorts a copy of the samples.
  LatencySummary Summarize() const;

 private:
  mutable std::mutex mu_;
  std::vector<int64_t> samples_;
};

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_COMMON_LATENCY_STATS_H_
