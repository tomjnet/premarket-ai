// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/mpmc_queue.h"

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <thread>
#include <vector>

#include "gtest/gtest.h"

namespace premarket::ingest {
namespace {

TEST(MpmcQueueTest, CapacityIsAPowerOfTwo) {
  EXPECT_EQ(MpmcQueue<int>(0).capacity(), 2u);
  EXPECT_EQ(MpmcQueue<int>(1).capacity(), 2u);
  EXPECT_EQ(MpmcQueue<int>(3).capacity(), 4u);
  EXPECT_EQ(MpmcQueue<int>(64).capacity(), 64u);
  EXPECT_EQ(MpmcQueue<int>(65).capacity(), 128u);
}

TEST(MpmcQueueTest, FifoOrderSingleThread) {
  MpmcQueue<int> queue(4);
  EXPECT_TRUE(queue.TryPush(1));
  EXPECT_TRUE(queue.TryPush(2));
  EXPECT_TRUE(queue.TryPush(3));
  int value = 0;
  ASSERT_TRUE(queue.TryPop(&value));
  EXPECT_EQ(value, 1);
  ASSERT_TRUE(queue.TryPop(&value));
  EXPECT_EQ(value, 2);
  ASSERT_TRUE(queue.TryPop(&value));
  EXPECT_EQ(value, 3);
}

TEST(MpmcQueueTest, FullAndEmpty) {
  MpmcQueue<int> queue(4);
  int value = 0;
  EXPECT_FALSE(queue.TryPop(&value));  // empty
  for (int i = 0; i < 4; ++i) EXPECT_TRUE(queue.TryPush(i));
  EXPECT_FALSE(queue.TryPush(99));  // full
  ASSERT_TRUE(queue.TryPop(&value));
  EXPECT_EQ(value, 0);
  EXPECT_TRUE(queue.TryPush(4));  // one free cell again
  for (int i = 1; i <= 4; ++i) {
    ASSERT_TRUE(queue.TryPop(&value));
    EXPECT_EQ(value, i);
  }
  EXPECT_FALSE(queue.TryPop(&value));
}

TEST(MpmcQueueTest, WrapsAroundManyLaps) {
  MpmcQueue<int64_t> queue(2);
  int64_t value = 0;
  for (int64_t i = 0; i < 10000; ++i) {
    ASSERT_TRUE(queue.TryPush(i));
    ASSERT_TRUE(queue.TryPop(&value));
    ASSERT_EQ(value, i);
  }
}

TEST(MpmcQueueTest, CarriesTrivialStructs) {
  struct Task {
    std::uint32_t index;
    int64_t enqueue_ns;
  };
  MpmcQueue<Task> queue(8);
  EXPECT_TRUE(queue.TryPush(Task{.index = 7, .enqueue_ns = 42}));
  Task task{};
  ASSERT_TRUE(queue.TryPop(&task));
  EXPECT_EQ(task.index, 7u);
  EXPECT_EQ(task.enqueue_ns, 42);
}

// Every value pushed by 4 producers is popped exactly once by 4 consumers
// through an 8-cell ring. Run under TSan by the tsan stage.
TEST(MpmcQueueTest, ManyProducersManyConsumers) {
  constexpr int kProducers = 4;
  constexpr int kConsumers = 4;
  constexpr int kPerProducer = 20000;
  MpmcQueue<int> queue(8);
  std::vector<std::atomic<int>> seen(kProducers * kPerProducer);
  std::atomic<int> popped{0};

  std::vector<std::thread> threads;
  for (int c = 0; c < kConsumers; ++c) {
    threads.emplace_back([&] {
      int value = 0;
      while (popped.load(std::memory_order_relaxed) <
             kProducers * kPerProducer) {
        if (queue.TryPop(&value)) {
          seen[static_cast<std::size_t>(value)].fetch_add(1);
          popped.fetch_add(1);
        } else {
          std::this_thread::yield();
        }
      }
    });
  }
  for (int p = 0; p < kProducers; ++p) {
    threads.emplace_back([&queue, p] {
      for (int i = 0; i < kPerProducer; ++i) {
        const int value = p * kPerProducer + i;
        while (!queue.TryPush(value)) std::this_thread::yield();
      }
    });
  }
  for (std::thread& thread : threads) thread.join();

  EXPECT_EQ(popped.load(), kProducers * kPerProducer);
  for (std::size_t i = 0; i < seen.size(); ++i) {
    ASSERT_EQ(seen[i].load(), 1) << "value " << i;
  }
  int value = 0;
  EXPECT_FALSE(queue.TryPop(&value));
}

}  // namespace
}  // namespace premarket::ingest
