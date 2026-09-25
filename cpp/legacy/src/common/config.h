// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Runtime configuration from environment variables (set in compose.yaml).
// PostgreSQL settings come from the standard libpq PG* variables.

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_COMMON_CONFIG_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_COMMON_CONFIG_H_

#include <cstddef>
#include <string>

#include "common/status.h"

namespace premarket {
namespace legacy {

struct Config {
  std::string feed_url;        // VENDOR_FEED_URL
  std::string pg_conninfo;     // LEGACY_PG_CONNINFO ("" = PG* env vars)
  std::string reports_dir;     // LEGACY_REPORTS_DIR
  std::string crontab_path;    // LEGACY_CRONTAB
  int workers;                 // LEGACY_WORKERS
  std::size_t queue_capacity;  // LEGACY_QUEUE_CAPACITY
  int dedup_window_days;       // LEGACY_DEDUP_WINDOW_DAYS
  int fetch_retries;           // LEGACY_FETCH_RETRIES
};

// Reads the environment and validates the numeric values.
StatusOr<Config> LoadConfigFromEnv();

// True for a real calendar date written as YYYY-MM-DD.
bool IsValidDate(const std::string& date);

// Today's date as YYYY-MM-DD in the process time zone (TZ, set to
// America/New_York in the container).
std::string TodayLocal();

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_COMMON_CONFIG_H_
