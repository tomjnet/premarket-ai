// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Persistent pool of std::jthread workers fed by the lock-free MpmcQueue.
//
// Between runs the workers sleep on an atomic epoch (C++20 atomic
// wait/notify, a futex on Linux), so an idle pool burns no CPU. Run() bumps
// the epoch, pushes one {index, enqueue time} task per item and one
// end-of-run marker per worker, then waits on a std::latch. During a run the
// workers spin on the queue with a CPU pause and bounded backoff. Tasks are
// a function pointer plus a void* context: no std::function, no allocation,
// no locks.

#ifndef PREMARKET_AI_CPP_INGEST_SRC_INGEST_WORKER_POOL_H_
#define PREMARKET_AI_CPP_INGEST_SRC_INGEST_WORKER_POOL_H_

#include <atomic>
#include <concepts>
#include <cstddef>
#include <cstdint>
#include <latch>
#include <memory>
#include <span>
#include <stop_token>
#include <thread>
#include <vector>

#include "common/latency.h"
#include "ingest/mpmc_queue.h"

namespace premarket::ingest {

struct WorkerPoolOptions {
  int workers = 4;                  // at least 1
  std::size_t queue_capacity = 64;  // rounded up to a power of two
  std::size_t max_tasks = 4096;     // queue-wait samples kept per worker
  bool pin_cpus = false;            // worker i -> CPU i % hardware threads
};

// Spin-then-yield backoff for a thread waiting on the queue.
class Backoff {
 public:
  void Pause();
  void Reset() { round_ = 0; }

 private:
  static constexpr int kMaxSpinRounds = 6;  // up to 2^6 CPU pauses
  int round_ = 0;
};

class WorkerPool {
 public:
  explicit WorkerPool(const WorkerPoolOptions& options);
  // Stops and joins the workers. Must not run concurrently with Run().
  ~WorkerPool();

  WorkerPool(const WorkerPool&) = delete;
  WorkerPool& operator=(const WorkerPool&) = delete;

  // Calls fn(index, worker) once for every index in [0, count), spread over
  // the workers, and returns when all calls are done. `worker` is in
  // [0, size()), so `fn` can use per-worker scratch state without locks.
  // Called from one thread at a time.
  template <typename F>
    requires std::invocable<F&, std::uint32_t, int>
  void Run(std::uint32_t count, F& fn) {
    RunErased(count, &Invoke<F>, static_cast<void*>(&fn));
  }

  int size() const { return static_cast<int>(threads_.size()); }
  std::size_t queue_capacity() const { return queue_.capacity(); }

  // Queue wait (enqueue -> dequeue, nanoseconds) of the last run, one
  // buffer per worker. Read only between runs.
  std::span<const SampleBuffer* const> wait_samples() const {
    return wait_views_;
  }

 private:
  using TaskFn = void (*)(void* context, std::uint32_t index, int worker);

  struct Task {
    std::uint32_t index;
    int64_t enqueue_ns;
  };
  static constexpr std::uint32_t kEndOfRun = UINT32_MAX;

  // Per-worker state on its own cache lines.
  struct alignas(kCacheLineSize) WorkerState {
    explicit WorkerState(std::size_t max_tasks) : wait(max_tasks) {}
    SampleBuffer wait;
  };

  template <typename F>
  static void Invoke(void* context, std::uint32_t index, int worker) {
    (*static_cast<F*>(context))(index, worker);
  }

  void RunErased(std::uint32_t count, TaskFn fn, void* context);
  void WorkerLoop(const std::stop_token& stop, int worker);
  void ProcessRun(int worker);

  const bool pin_cpus_;
  MpmcQueue<Task> queue_;
  std::vector<WorkerState> states_;
  std::vector<const SampleBuffer*> wait_views_;

  // The current run. Written by Run() before the epoch is bumped (release)
  // and read by workers after they see the new epoch (acquire).
  TaskFn fn_ = nullptr;
  void* context_ = nullptr;
  std::latch* done_ = nullptr;

  alignas(kCacheLineSize) std::atomic<std::uint64_t> epoch_{0};
  // Last member: destroyed (joined) before everything the workers use.
  std::vector<std::jthread> threads_;
};

}  // namespace premarket::ingest

#endif  // PREMARKET_AI_CPP_INGEST_SRC_INGEST_WORKER_POOL_H_
