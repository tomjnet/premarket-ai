// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/worker_pool.h"

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "common/latency.h"
#include "gtest/gtest.h"

namespace premarket::ingest {
namespace {

TEST(WorkerPoolTest, RunsEveryIndexExactlyOnce) {
  WorkerPool pool({.workers = 4, .queue_capacity = 8, .max_tasks = 1000});
  EXPECT_EQ(pool.size(), 4);
  EXPECT_EQ(pool.queue_capacity(), 8u);
  std::vector<std::atomic<int>> hits(1000);
  auto task = [&hits](std::uint32_t index, int /*worker*/) {
    hits[index].fetch_add(1, std::memory_order_relaxed);
  };
  pool.Run(1000, task);
  for (std::size_t i = 0; i < hits.size(); ++i) {
    ASSERT_EQ(hits[i].load(), 1) << "index " << i;
  }
}

TEST(WorkerPoolTest, TasksWriteTheirOwnSlots) {
  WorkerPool pool({.workers = 3, .queue_capacity = 16, .max_tasks = 500});
  std::vector<int> out(500, 0);
  auto task = [&out](std::uint32_t index, int /*worker*/) {
    out[index] = static_cast<int>(index) * 2;
  };
  pool.Run(500, task);
  for (std::size_t i = 0; i < out.size(); ++i) {
    EXPECT_EQ(out[i], static_cast<int>(i) * 2);
  }
}

TEST(WorkerPoolTest, WorkerIdsAreInRange) {
  WorkerPool pool({.workers = 4, .queue_capacity = 4, .max_tasks = 200});
  std::vector<int> worker_of(200, -1);
  auto task = [&worker_of](std::uint32_t index, int worker) {
    worker_of[index] = worker;
  };
  pool.Run(200, task);
  for (const int worker : worker_of) {
    EXPECT_GE(worker, 0);
    EXPECT_LT(worker, 4);
  }
}

TEST(WorkerPoolTest, ManyRunsReuseTheSameThreads) {
  WorkerPool pool({.workers = 4, .queue_capacity = 2, .max_tasks = 64});
  std::vector<int64_t> sums(64, 0);
  for (int run = 0; run < 500; ++run) {
    const auto count = static_cast<std::uint32_t>(run % 64);
    auto task = [&sums, run](std::uint32_t index, int /*worker*/) {
      sums[index] += run;
    };
    pool.Run(count, task);
  }
  int64_t expected = 0;
  for (int run = 0; run < 500; ++run) {
    if (run % 64 > 5) expected += run;
  }
  EXPECT_EQ(sums[5], expected);
}

TEST(WorkerPoolTest, RecordsOneQueueWaitPerTask) {
  WorkerPool pool({.workers = 2, .queue_capacity = 4, .max_tasks = 100});
  auto task = [](std::uint32_t /*index*/, int /*worker*/) {};
  pool.Run(100, task);
  std::size_t samples = 0;
  for (const SampleBuffer* buffer : pool.wait_samples()) {
    samples += buffer->samples().size();
    for (const int64_t wait : buffer->samples()) EXPECT_GE(wait, 0);
  }
  EXPECT_EQ(samples, 100u);
  pool.Run(10, task);  // cleared per run
  samples = 0;
  for (const SampleBuffer* buffer : pool.wait_samples()) {
    samples += buffer->samples().size();
  }
  EXPECT_EQ(samples, 10u);
}

TEST(WorkerPoolTest, EmptyRunAndAtLeastOneWorker) {
  WorkerPool pool({.workers = 0, .queue_capacity = 1, .max_tasks = 1});
  EXPECT_EQ(pool.size(), 1);
  int calls = 0;
  auto task = [&calls](std::uint32_t /*index*/, int /*worker*/) { ++calls; };
  pool.Run(0, task);
  pool.Run(3, task);
  EXPECT_EQ(calls, 3);
}

TEST(WorkerPoolTest, StopsIdleWorkers) {
  // Constructing and destroying pools must not hang, with or without runs.
  for (int i = 0; i < 20; ++i) {
    WorkerPool pool({.workers = 4, .queue_capacity = 8, .max_tasks = 8});
    if (i % 2 == 0) {
      auto task = [](std::uint32_t /*index*/, int /*worker*/) {};
      pool.Run(8, task);
    }
  }
}

TEST(WorkerPoolTest, CpuPinningStillRunsEverything) {
  WorkerPool pool(
      {.workers = 2, .queue_capacity = 4, .max_tasks = 50, .pin_cpus = true});
  std::atomic<int> done{0};
  auto task = [&done](std::uint32_t /*index*/, int /*worker*/) {
    done.fetch_add(1);
  };
  pool.Run(50, task);
  EXPECT_EQ(done.load(), 50);
}

}  // namespace
}  // namespace premarket::ingest
