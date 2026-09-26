// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "common/latency.h"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <span>

namespace premarket::ingest {

int64_t Percentile(std::span<const int64_t> sorted, double fraction) {
  if (sorted.empty()) return 0;
  const double rank = std::ceil(fraction * static_cast<double>(sorted.size()));
  std::size_t index = rank < 1.0 ? 0 : static_cast<std::size_t>(rank) - 1;
  if (index >= sorted.size()) index = sorted.size() - 1;
  return sorted[index];
}

LatencySummary Summarize(std::span<int64_t> samples) {
  std::sort(samples.begin(), samples.end());
  LatencySummary summary;
  summary.count = samples.size();
  if (samples.empty()) return summary;
  summary.p50 = Percentile(samples, 0.50);
  summary.p99 = Percentile(samples, 0.99);
  summary.p999 = Percentile(samples, 0.999);
  summary.max = samples.back();
  return summary;
}

LatencySummary LatencyMerger::Summarize(
    std::span<const SampleBuffer* const> buffers, int64_t divisor) {
  merged_.clear();
  for (const SampleBuffer* buffer : buffers) {
    for (const int64_t sample : buffer->samples()) {
      merged_.push_back(sample / divisor);
    }
  }
  return ingest::Summarize(merged_);
}

}  // namespace premarket::ingest
