// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/bounded_queue.h"

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <thread>
#include <vector>

#include "gtest/gtest.h"

namespace premarket {
namespace legacy {
namespace {

TEST(BoundedQueueTest, FifoOrder) {
  BoundedQueue<int> queue(4);
  EXPECT_TRUE(queue.Push(1));
  EXPECT_TRUE(queue.Push(2));
  EXPECT_TRUE(queue.Push(3));
  EXPECT_EQ(queue.size(), 3u);
  int value = 0;
  ASSERT_TRUE(queue.Pop(&value));
  EXPECT_EQ(value, 1);
  ASSERT_TRUE(queue.Pop(&value));
  EXPECT_EQ(value, 2);
}

TEST(BoundedQueueTest, ZeroCapacityBecomesOne) {
  BoundedQueue<int> queue(0);
  EXPECT_EQ(queue.capacity(), 1u);
}

TEST(BoundedQueueTest, CloseDrainsThenStops) {
  BoundedQueue<int> queue(4);
  queue.Push(7);
  queue.Close();
  EXPECT_FALSE(queue.Push(8));
  int value = 0;
  ASSERT_TRUE(queue.Pop(&value));
  EXPECT_EQ(value, 7);
  EXPECT_FALSE(queue.Pop(&value));
}

TEST(BoundedQueueTest, CloseWakesBlockedConsumer) {
  BoundedQueue<int> queue(1);
  std::atomic<bool> returned(false);
  std::thread consumer([&queue, &returned]() {
    int value = 0;
    EXPECT_FALSE(queue.Pop(&value));
    returned = true;
  });
  queue.Close();
  consumer.join();
  EXPECT_TRUE(returned);
}

TEST(BoundedQueueTest, ManyProducersManyConsumers) {
  const int kProducers = 4;
  const int kConsumers = 4;
  const int kPerProducer = 2000;
  BoundedQueue<int> queue(8);
  std::atomic<int64_t> sum(0);
  std::atomic<int> count(0);

  std::vector<std::thread> consumers;
  for (int c = 0; c < kConsumers; ++c) {
    consumers.push_back(std::thread([&queue, &sum, &count]() {
      int value = 0;
      while (queue.Pop(&value)) {
        sum += value;
        ++count;
      }
    }));
  }
  std::vector<std::thread> producers;
  for (int p = 0; p < kProducers; ++p) {
    producers.push_back(std::thread([&queue]() {
      for (int i = 1; i <= kPerProducer; ++i) queue.Push(i);
    }));
  }
  for (size_t i = 0; i < producers.size(); ++i) producers[i].join();
  queue.Close();
  for (size_t i = 0; i < consumers.size(); ++i) consumers[i].join();

  const int64_t expected =
      static_cast<int64_t>(kProducers) * kPerProducer * (kPerProducer + 1) / 2;
  EXPECT_EQ(count.load(), kProducers * kPerProducer);
  EXPECT_EQ(sum.load(), expected);
}

}  // namespace
}  // namespace legacy
}  // namespace premarket
