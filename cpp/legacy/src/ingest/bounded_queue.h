// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Classic blocking bounded queue: std::mutex + two condition variables.
// This is the measured baseline the C++20 lock-free ring has to beat.

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_INGEST_BOUNDED_QUEUE_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_INGEST_BOUNDED_QUEUE_H_

#include <condition_variable>
#include <cstddef>
#include <deque>
#include <mutex>
#include <utility>

namespace premarket {
namespace legacy {

template <typename T>
class BoundedQueue {
 public:
  explicit BoundedQueue(std::size_t capacity)
      : capacity_(capacity == 0 ? 1 : capacity), closed_(false) {}

  BoundedQueue(const BoundedQueue&) = delete;
  BoundedQueue& operator=(const BoundedQueue&) = delete;

  // Blocks while the queue is full. Returns false (and drops `item`) if the
  // queue is closed.
  bool Push(T item) {
    std::unique_lock<std::mutex> lock(mu_);
    not_full_.wait(lock,
                   [this] { return closed_ || items_.size() < capacity_; });
    if (closed_) return false;
    items_.push_back(std::move(item));
    lock.unlock();
    not_empty_.notify_one();
    return true;
  }

  // Blocks while the queue is empty. Returns false once the queue is closed
  // and fully drained.
  bool Pop(T* item) {
    std::unique_lock<std::mutex> lock(mu_);
    not_empty_.wait(lock, [this] { return closed_ || !items_.empty(); });
    if (items_.empty()) return false;
    *item = std::move(items_.front());
    items_.pop_front();
    lock.unlock();
    not_full_.notify_one();
    return true;
  }

  // Wakes every waiter. Items already queued can still be popped.
  void Close() {
    {
      std::lock_guard<std::mutex> lock(mu_);
      closed_ = true;
    }
    not_empty_.notify_all();
    not_full_.notify_all();
  }

  std::size_t size() const {
    std::lock_guard<std::mutex> lock(mu_);
    return items_.size();
  }

  std::size_t capacity() const { return capacity_; }

 private:
  const std::size_t capacity_;
  mutable std::mutex mu_;
  std::condition_variable not_empty_;
  std::condition_variable not_full_;
  std::deque<T> items_;
  bool closed_;
};

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_INGEST_BOUNDED_QUEUE_H_
