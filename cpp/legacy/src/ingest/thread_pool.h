// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Fixed-size pool of std::thread workers fed by a BoundedQueue of
// std::function tasks (one heap allocation per task, as old code does).

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_INGEST_THREAD_POOL_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_INGEST_THREAD_POOL_H_

#include <cstddef>
#include <functional>
#include <thread>
#include <vector>

#include "ingest/bounded_queue.h"

namespace premarket {
namespace legacy {

class ThreadPool {
 public:
  // Starts `num_threads` workers (at least 1).
  ThreadPool(int num_threads, std::size_t queue_capacity);
  ~ThreadPool();

  ThreadPool(const ThreadPool&) = delete;
  ThreadPool& operator=(const ThreadPool&) = delete;

  // Blocks while the queue is full. Returns false after Shutdown().
  bool Submit(std::function<void()> task);

  // Runs every queued task, then joins the workers. Idempotent. Must be
  // called from the thread that owns the pool.
  void Shutdown();

  int size() const { return static_cast<int>(workers_.size()); }

 private:
  void WorkerLoop();

  BoundedQueue<std::function<void()>> queue_;
  std::vector<std::thread> workers_;
  bool shut_down_;
};

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_INGEST_THREAD_POOL_H_
