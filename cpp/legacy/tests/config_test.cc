// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "common/config.h"

#include <stdlib.h>

#include "gtest/gtest.h"

namespace premarket {
namespace legacy {
namespace {

TEST(IsValidDateTest, AcceptsRealDates) {
  EXPECT_TRUE(IsValidDate("2026-09-24"));
  EXPECT_TRUE(IsValidDate("2028-02-29"));
  EXPECT_TRUE(IsValidDate("2026-12-31"));
}

TEST(IsValidDateTest, RejectsBadDates) {
  EXPECT_FALSE(IsValidDate(""));
  EXPECT_FALSE(IsValidDate("2026-9-24"));
  EXPECT_FALSE(IsValidDate("2026/09/24"));
  EXPECT_FALSE(IsValidDate("2026-13-01"));
  EXPECT_FALSE(IsValidDate("2026-02-29"));
  EXPECT_FALSE(IsValidDate("2026-04-31"));
  EXPECT_FALSE(IsValidDate("2026-00-10"));
  EXPECT_FALSE(IsValidDate("abcd-ef-gh"));
}

TEST(TodayLocalTest, IsAValidDate) { EXPECT_TRUE(IsValidDate(TodayLocal())); }

TEST(LoadConfigTest, DefaultsAndOverrides) {
  unsetenv("LEGACY_WORKERS");
  unsetenv("LEGACY_QUEUE_CAPACITY");
  StatusOr<Config> config = LoadConfigFromEnv();
  ASSERT_TRUE(config.ok()) << config.status().ToString();
  EXPECT_EQ(config.value().workers, 4);
  EXPECT_EQ(config.value().queue_capacity, 64u);

  setenv("LEGACY_WORKERS", "8", 1);
  config = LoadConfigFromEnv();
  ASSERT_TRUE(config.ok());
  EXPECT_EQ(config.value().workers, 8);

  setenv("LEGACY_WORKERS", "eight", 1);
  EXPECT_FALSE(LoadConfigFromEnv().ok());
  setenv("LEGACY_WORKERS", "0", 1);
  EXPECT_FALSE(LoadConfigFromEnv().ok());
  unsetenv("LEGACY_WORKERS");
}

}  // namespace
}  // namespace legacy
}  // namespace premarket
