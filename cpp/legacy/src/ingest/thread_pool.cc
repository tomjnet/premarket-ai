// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/thread_pool.h"

#include <cstddef>
#include <functional>
#include <thread>
#include <utility>

namespace premarket {
namespace legacy {

ThreadPool::ThreadPool(int num_threads, std::size_t queue_capacity)
    : queue_(queue_capacity), shut_down_(false) {
  const int count = num_threads < 1 ? 1 : num_threads;
  workers_.reserve(static_cast<std::size_t>(count));
  for (int i = 0; i < count; ++i) {
    workers_.push_back(std::thread(&ThreadPool::WorkerLoop, this));
  }
}

ThreadPool::~ThreadPool() { Shutdown(); }

bool ThreadPool::Submit(std::function<void()> task) {
  return queue_.Push(std::move(task));
}

void ThreadPool::Shutdown() {
  if (shut_down_) return;
  shut_down_ = true;
  queue_.Close();
  for (std::size_t i = 0; i < workers_.size(); ++i) {
    workers_[i].join();
  }
}

void ThreadPool::WorkerLoop() {
  std::function<void()> task;
  while (queue_.Pop(&task)) {
    task();
    task = nullptr;
  }
}

}  // namespace legacy
}  // namespace premarket
