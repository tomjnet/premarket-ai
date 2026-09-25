// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "common/latency_stats.h"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <vector>

namespace premarket {
namespace legacy {

int64_t Percentile(const std::vector<int64_t>& sorted, double fraction) {
  if (sorted.empty()) return 0;
  const double rank = std::ceil(fraction * static_cast<double>(sorted.size()));
  std::size_t index = rank < 1.0 ? 0 : static_cast<std::size_t>(rank) - 1;
  if (index >= sorted.size()) index = sorted.size() - 1;
  return sorted[index];
}

void LatencyRecorder::Record(int64_t micros) {
  std::lock_guard<std::mutex> lock(mu_);
  samples_.push_back(micros);
}

LatencySummary LatencyRecorder::Summarize() const {
  std::vector<int64_t> sorted;
  {
    std::lock_guard<std::mutex> lock(mu_);
    sorted = samples_;
  }
  std::sort(sorted.begin(), sorted.end());
  LatencySummary summary;
  summary.count = sorted.size();
  if (sorted.empty()) return summary;
  summary.p50_us = Percentile(sorted, 0.50);
  summary.p99_us = Percentile(sorted, 0.99);
  summary.p999_us = Percentile(sorted, 0.999);
  summary.max_us = sorted.back();
  return summary;
}

}  // namespace legacy
}  // namespace premarket
