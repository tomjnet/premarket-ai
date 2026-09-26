// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Runtime configuration from environment variables (set in compose.yaml).
// PostgreSQL settings come from the standard libpq PG* variables.

#ifndef PREMARKET_AI_CPP_INGEST_SRC_COMMON_CONFIG_H_
#define PREMARKET_AI_CPP_INGEST_SRC_COMMON_CONFIG_H_

#include <cstddef>
#include <string>
#include <string_view>

#include "absl/status/statusor.h"

namespace premarket::ingest {

struct Config {
  std::string feed_url;             // VENDOR_FEED_URL
  std::string pg_conninfo;          // INGEST_PG_CONNINFO ("" = PG* env)
  std::string schema_file;          // INGEST_SCHEMA_FILE
  std::string crontab_path;         // INGEST_CRONTAB
  int workers = 4;                  // INGEST_WORKERS
  std::size_t queue_capacity = 64;  // INGEST_QUEUE_CAPACITY, power of two
  int dedup_window_days = 7;        // INGEST_DEDUP_WINDOW_DAYS
  int fetch_retries = 5;            // INGEST_FETCH_RETRIES
  std::size_t max_items = 4096;     // INGEST_MAX_ITEMS
  std::size_t max_feed_bytes = 64u << 20;  // INGEST_MAX_FEED_BYTES
  bool cpu_affinity = false;               // INGEST_CPU_AFFINITY
  int parity_wait_s = 600;                 // INGEST_PARITY_WAIT_S
};

// Reads the environment and validates the numeric values.
absl::StatusOr<Config> LoadConfigFromEnv();

// True for a real calendar date written as YYYY-MM-DD.
bool IsValidDate(std::string_view date);

// Today's date as YYYY-MM-DD in the process time zone (TZ, set to
// America/New_York in the container).
std::string TodayLocal();

}  // namespace premarket::ingest

#endif  // PREMARKET_AI_CPP_INGEST_SRC_COMMON_CONFIG_H_
