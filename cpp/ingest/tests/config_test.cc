// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "common/config.h"

#include <stdlib.h>

#include <string>

#include "absl/status/statusor.h"
#include "gtest/gtest.h"

namespace premarket::ingest {
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
  EXPECT_FALSE(IsValidDate("1969-12-31"));
}

TEST(TodayLocalTest, IsAValidDate) { EXPECT_TRUE(IsValidDate(TodayLocal())); }

TEST(LoadConfigTest, Defaults) {
  for (const char* name :
       {"VENDOR_FEED_URL", "INGEST_PG_CONNINFO", "INGEST_WORKERS",
        "INGEST_QUEUE_CAPACITY", "INGEST_DEDUP_WINDOW_DAYS",
        "INGEST_FETCH_RETRIES", "INGEST_MAX_ITEMS", "INGEST_MAX_FEED_BYTES",
        "INGEST_CPU_AFFINITY", "INGEST_SCHEMA_FILE", "INGEST_CRONTAB",
        "INGEST_PARITY_WAIT_S"}) {
    unsetenv(name);
  }
  const absl::StatusOr<Config> config = LoadConfigFromEnv();
  ASSERT_TRUE(config.ok()) << config.status();
  EXPECT_EQ(config->feed_url, "http://vendor-sim:8080/feed");
  EXPECT_EQ(config->pg_conninfo, "");
  EXPECT_EQ(config->workers, 4);
  EXPECT_EQ(config->queue_capacity, 64u);
  EXPECT_EQ(config->dedup_window_days, 7);
  EXPECT_EQ(config->fetch_retries, 5);
  EXPECT_EQ(config->max_items, 4096u);
  EXPECT_EQ(config->max_feed_bytes, 67108864u);
  EXPECT_FALSE(config->cpu_affinity);
  EXPECT_EQ(config->schema_file, "/etc/premarket/ingest-schema.sql");
  EXPECT_EQ(config->crontab_path, "/etc/premarket/crontab");
  EXPECT_EQ(config->parity_wait_s, 600);
}

TEST(LoadConfigTest, OverridesAndValidation) {
  setenv("INGEST_WORKERS", "8", 1);
  absl::StatusOr<Config> config = LoadConfigFromEnv();
  ASSERT_TRUE(config.ok());
  EXPECT_EQ(config->workers, 8);

  setenv("INGEST_WORKERS", "eight", 1);
  EXPECT_FALSE(LoadConfigFromEnv().ok());
  setenv("INGEST_WORKERS", "0", 1);
  EXPECT_FALSE(LoadConfigFromEnv().ok());
  setenv("INGEST_WORKERS", "65", 1);
  config = LoadConfigFromEnv();
  ASSERT_FALSE(config.ok());
  EXPECT_NE(config.status().message().find("INGEST_WORKERS"),
            std::string::npos);
  unsetenv("INGEST_WORKERS");

  setenv("INGEST_CPU_AFFINITY", "1", 1);
  config = LoadConfigFromEnv();
  ASSERT_TRUE(config.ok());
  EXPECT_TRUE(config->cpu_affinity);
  setenv("INGEST_CPU_AFFINITY", "2", 1);
  EXPECT_FALSE(LoadConfigFromEnv().ok());
  unsetenv("INGEST_CPU_AFFINITY");

  setenv("INGEST_DEDUP_WINDOW_DAYS", "366", 1);
  EXPECT_FALSE(LoadConfigFromEnv().ok());
  unsetenv("INGEST_DEDUP_WINDOW_DAYS");
}

TEST(LoadConfigTest, QueueCapacityIsAPowerOfTwo) {
  setenv("INGEST_QUEUE_CAPACITY", "100", 1);
  absl::StatusOr<Config> config = LoadConfigFromEnv();
  ASSERT_TRUE(config.ok());
  EXPECT_EQ(config->queue_capacity, 128u);
  setenv("INGEST_QUEUE_CAPACITY", "1", 1);
  config = LoadConfigFromEnv();
  ASSERT_TRUE(config.ok());
  EXPECT_EQ(config->queue_capacity, 2u);
  unsetenv("INGEST_QUEUE_CAPACITY");
}

}  // namespace
}  // namespace premarket::ingest
