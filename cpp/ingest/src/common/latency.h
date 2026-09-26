// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Latency samples and p50 / p99 / p99.9 summaries. Unlike legacy's mutex +
// growing vector, every worker owns a preallocated sample array (no locks,
// no allocation while recording); the arrays are merged after a run.

#ifndef PREMARKET_AI_CPP_INGEST_SRC_COMMON_LATENCY_H_
#define PREMARKET_AI_CPP_INGEST_SRC_COMMON_LATENCY_H_

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace premarket::ingest {

struct LatencySummary {
  std::size_t count = 0;
  int64_t p50 = 0;
  int64_t p99 = 0;
  int64_t p999 = 0;
  int64_t max = 0;
};

// Monotonic clock in nanoseconds (vDSO, no syscall).
inline int64_t NowNanos() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

// Nearest-rank percentile of an ascending-sorted span; 0 when empty.
// `fraction` is in (0, 1], for example 0.99. Same rule as legacy.
int64_t Percentile(std::span<const int64_t> sorted, double fraction);

// Sorts `samples` in place and summarizes them.
LatencySummary Summarize(std::span<int64_t> samples);

// A fixed-capacity sample array owned by one thread. Record() never
// allocates; samples beyond the capacity are counted as dropped.
class SampleBuffer {
 public:
  explicit SampleBuffer(std::size_t capacity) : samples_(capacity) {}

  void Record(int64_t value) {
    if (size_ < samples_.size()) {
      samples_[size_++] = value;
    } else {
      ++dropped_;
    }
  }
  void Clear() {
    size_ = 0;
    dropped_ = 0;
  }

  std::span<const int64_t> samples() const { return {samples_.data(), size_}; }
  std::size_t dropped() const { return dropped_; }

 private:
  std::vector<int64_t> samples_;
  std::size_t size_ = 0;
  std::size_t dropped_ = 0;
};

// Merges per-thread buffers into one preallocated array, then summarizes.
class LatencyMerger {
 public:
  explicit LatencyMerger(std::size_t capacity) { merged_.reserve(capacity); }

  // `divisor` scales every sample (1000 turns nanoseconds into
  // microseconds, truncating like legacy's duration_cast).
  LatencySummary Summarize(std::span<const SampleBuffer* const> buffers,
                           int64_t divisor);

 private:
  std::vector<int64_t> merged_;
};

}  // namespace premarket::ingest

#endif  // PREMARKET_AI_CPP_INGEST_SRC_COMMON_LATENCY_H_
