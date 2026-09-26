// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Bounded lock-free multi-producer multi-consumer ring buffer (Dmitry
// Vyukov's design). Each cell carries a sequence number that tells
// producers and consumers whose turn it is, so a push or pop is one CAS on
// the shared position plus one release store on the cell. The cells are
// allocated once in the constructor; TryPush / TryPop never allocate, lock
// or block. This replaces legacy's mutex + condition-variable queue.

#ifndef PREMARKET_AI_CPP_INGEST_SRC_INGEST_MPMC_QUEUE_H_
#define PREMARKET_AI_CPP_INGEST_SRC_INGEST_MPMC_QUEUE_H_

#include <algorithm>
#include <atomic>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <type_traits>
#include <vector>

namespace premarket::ingest {

// One cache line; keeps hot atomics written by different threads apart.
inline constexpr std::size_t kCacheLineSize = 64;

template <typename T>
  requires std::is_trivially_copyable_v<T>
class MpmcQueue {
 public:
  // Capacity is `min_capacity` rounded up to a power of two (at least 2).
  explicit MpmcQueue(std::size_t min_capacity)
      : mask_(std::bit_ceil(std::max<std::size_t>(min_capacity, 2)) - 1),
        cells_(mask_ + 1) {
    for (std::size_t i = 0; i <= mask_; ++i) {
      cells_[i].sequence.store(i, std::memory_order_relaxed);
    }
  }

  MpmcQueue(const MpmcQueue&) = delete;
  MpmcQueue& operator=(const MpmcQueue&) = delete;

  // Returns false when the queue is full.
  bool TryPush(const T& value) {
    std::size_t pos = enqueue_pos_.load(std::memory_order_relaxed);
    Cell* cell = nullptr;
    while (true) {
      cell = &cells_[pos & mask_];
      const std::size_t seq = cell->sequence.load(std::memory_order_acquire);
      const auto diff =
          static_cast<std::ptrdiff_t>(seq) - static_cast<std::ptrdiff_t>(pos);
      if (diff == 0) {
        if (enqueue_pos_.compare_exchange_weak(pos, pos + 1,
                                               std::memory_order_relaxed)) {
          break;
        }
      } else if (diff < 0) {
        return false;  // the cell still holds last lap's value: full
      } else {
        pos = enqueue_pos_.load(std::memory_order_relaxed);
      }
    }
    cell->value = value;
    cell->sequence.store(pos + 1, std::memory_order_release);
    return true;
  }

  // Returns false when the queue is empty.
  bool TryPop(T* value) {
    std::size_t pos = dequeue_pos_.load(std::memory_order_relaxed);
    Cell* cell = nullptr;
    while (true) {
      cell = &cells_[pos & mask_];
      const std::size_t seq = cell->sequence.load(std::memory_order_acquire);
      const auto diff = static_cast<std::ptrdiff_t>(seq) -
                        static_cast<std::ptrdiff_t>(pos + 1);
      if (diff == 0) {
        if (dequeue_pos_.compare_exchange_weak(pos, pos + 1,
                                               std::memory_order_relaxed)) {
          break;
        }
      } else if (diff < 0) {
        return false;  // nothing published in this cell yet: empty
      } else {
        pos = dequeue_pos_.load(std::memory_order_relaxed);
      }
    }
    *value = cell->value;
    cell->sequence.store(pos + mask_ + 1, std::memory_order_release);
    return true;
  }

  std::size_t capacity() const { return mask_ + 1; }

 private:
  // Each cell on its own cache line, so neighbouring producers and
  // consumers do not false-share.
  struct alignas(kCacheLineSize) Cell {
    std::atomic<std::size_t> sequence{0};
    T value{};
  };

  const std::size_t mask_;
  std::vector<Cell> cells_;  // sized once, never resized
  // Producers and consumers each spin on their own line.
  alignas(kCacheLineSize) std::atomic<std::size_t> enqueue_pos_{0};
  alignas(kCacheLineSize) std::atomic<std::size_t> dequeue_pos_{0};
};

}  // namespace premarket::ingest

#endif  // PREMARKET_AI_CPP_INGEST_SRC_INGEST_MPMC_QUEUE_H_
