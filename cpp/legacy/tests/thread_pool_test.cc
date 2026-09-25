// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/thread_pool.h"

#include <atomic>
#include <cstddef>
#include <vector>

#include "gtest/gtest.h"

namespace premarket {
namespace legacy {
namespace {

TEST(ThreadPoolTest, RunsEveryTask) {
  std::atomic<int> done(0);
  {
    ThreadPool pool(4, 2);
    EXPECT_EQ(pool.size(), 4);
    for (int i = 0; i < 1000; ++i) {
      ASSERT_TRUE(pool.Submit([&done]() { ++done; }));
    }
    pool.Shutdown();
  }
  EXPECT_EQ(done.load(), 1000);
}

TEST(ThreadPoolTest, TasksWriteTheirOwnSlots) {
  std::vector<int> out(500, 0);
  ThreadPool pool(3, 16);
  for (int i = 0; i < 500; ++i) {
    int* slot = &out[static_cast<size_t>(i)];
    pool.Submit([slot, i]() { *slot = i * 2; });
  }
  pool.Shutdown();
  for (int i = 0; i < 500; ++i) EXPECT_EQ(out[static_cast<size_t>(i)], i * 2);
}

TEST(ThreadPoolTest, SubmitAfterShutdownFails) {
  ThreadPool pool(1, 1);
  pool.Shutdown();
  pool.Shutdown();  // idempotent
  EXPECT_FALSE(pool.Submit([]() {}));
}

TEST(ThreadPoolTest, AtLeastOneWorker) {
  ThreadPool pool(0, 1);
  EXPECT_EQ(pool.size(), 1);
}

}  // namespace
}  // namespace legacy
}  // namespace premarket
