// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/worker_pool.h"

#include <pthread.h>
#include <sched.h>

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <latch>
#include <stop_token>
#include <thread>

#include "absl/log/log.h"
#include "common/latency.h"

#if defined(__x86_64__) || defined(__i386__)
#include <immintrin.h>
#endif

namespace premarket::ingest {
namespace {

// Tells the CPU this is a spin-wait loop (saves power, frees the sibling
// hyper-thread).
inline void CpuRelax() {
#if defined(__x86_64__) || defined(__i386__)
  _mm_pause();
#elif defined(__aarch64__)
  asm volatile("yield");
#endif
}

// Pins the calling thread to CPU `worker % hardware threads`. Runs once at
// thread start; failure only costs locality, so it is logged, not fatal.
void PinToCpu(int worker) {
  const unsigned int cpus = std::max(1u, std::thread::hardware_concurrency());
  const auto cpu = static_cast<unsigned int>(worker) % cpus;
  cpu_set_t set;
  CPU_ZERO(&set);
  CPU_SET(cpu, &set);
  const int error = pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
  if (error != 0) {
    LOG(WARNING) << "worker " << worker << ": cannot pin to CPU " << cpu
                 << " (error " << error << ")";
  }
}

}  // namespace

void Backoff::Pause() {
  if (round_ < kMaxSpinRounds) {
    for (int i = 0; i < (1 << round_); ++i) CpuRelax();
    ++round_;
  } else {
    std::this_thread::yield();
  }
}

WorkerPool::WorkerPool(const WorkerPoolOptions& options)
    : pin_cpus_(options.pin_cpus), queue_(options.queue_capacity) {
  const int count = std::max(1, options.workers);
  // Every buffer exists before any thread starts; nothing reallocates later.
  states_.reserve(static_cast<std::size_t>(count));
  wait_views_.reserve(static_cast<std::size_t>(count));
  for (int i = 0; i < count; ++i) {
    states_.emplace_back(options.max_tasks);
  }
  for (const WorkerState& state : states_) wait_views_.push_back(&state.wait);
  threads_.reserve(static_cast<std::size_t>(count));
  for (int i = 0; i < count; ++i) {
    threads_.emplace_back(
        [this, i](const std::stop_token& stop) { WorkerLoop(stop, i); });
  }
}

WorkerPool::~WorkerPool() {
  for (std::jthread& thread : threads_) thread.request_stop();
  epoch_.fetch_add(1, std::memory_order_release);
  epoch_.notify_all();
  // threads_ joins in its destructor, before the other members go away.
}

void WorkerPool::RunErased(std::uint32_t count, TaskFn fn, void* context) {
  // One count per task plus one per end-of-run marker: when the latch
  // opens, every worker has finished this run and gone back to sleep, so
  // the next run can safely overwrite fn_ / context_ / done_.
  std::latch done(static_cast<std::ptrdiff_t>(count) + size());
  fn_ = fn;
  context_ = context;
  done_ = &done;
  epoch_.fetch_add(1, std::memory_order_release);
  epoch_.notify_all();

  Backoff backoff;
  for (std::uint32_t i = 0; i < count; ++i) {
    const Task task{.index = i, .enqueue_ns = NowNanos()};
    while (!queue_.TryPush(task)) backoff.Pause();
    backoff.Reset();
  }
  for (int i = 0; i < size(); ++i) {
    const Task end{.index = kEndOfRun, .enqueue_ns = 0};
    while (!queue_.TryPush(end)) backoff.Pause();
    backoff.Reset();
  }
  done.wait();
}

void WorkerPool::WorkerLoop(const std::stop_token& stop, int worker) {
  if (pin_cpus_) PinToCpu(worker);
  std::uint64_t seen = 0;
  while (true) {
    epoch_.wait(seen, std::memory_order_acquire);  // sleeps while idle
    seen = epoch_.load(std::memory_order_acquire);
    if (stop.stop_requested()) return;
    ProcessRun(worker);
  }
}

void WorkerPool::ProcessRun(int worker) {
  const TaskFn fn = fn_;
  void* const context = context_;
  std::latch* const done = done_;
  SampleBuffer& wait = states_[static_cast<std::size_t>(worker)].wait;
  wait.Clear();

  Backoff backoff;
  Task task{};
  while (true) {
    if (!queue_.TryPop(&task)) {
      backoff.Pause();
      continue;
    }
    backoff.Reset();
    if (task.index == kEndOfRun) {
      done->count_down();  // last touch of this run's state
      return;
    }
    wait.Record(NowNanos() - task.enqueue_ns);
    fn(context, task.index, worker);
    done->count_down();
  }
}

}  // namespace premarket::ingest
