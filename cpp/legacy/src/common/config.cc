// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "common/config.h"

#include <stdlib.h>
#include <time.h>

#include <cstddef>
#include <cstdint>
#include <string>

namespace premarket {
namespace legacy {
namespace {

std::string GetEnv(const char* name, const char* fallback) {
  const char* value = getenv(name);
  return (value != nullptr && value[0] != '\0') ? value : fallback;
}

// Parses a base-10 integer in [min_value, max_value].
Status GetEnvInt(const char* name, int fallback, int min_value, int max_value,
                 int* out) {
  const std::string text = GetEnv(name, "");
  if (text.empty()) {
    *out = fallback;
    return OkStatus();
  }
  char* end = nullptr;
  const int64_t parsed = strtol(text.c_str(), &end, 10);
  if (end == text.c_str() || *end != '\0' || parsed < min_value ||
      parsed > max_value) {
    return InvalidArgumentError(std::string(name) + " must be an integer in [" +
                                std::to_string(min_value) + ", " +
                                std::to_string(max_value) + "], got '" + text +
                                "'");
  }
  *out = static_cast<int>(parsed);
  return OkStatus();
}

bool IsLeapYear(int year) {
  return (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
}

}  // namespace

StatusOr<Config> LoadConfigFromEnv() {
  Config config;
  config.feed_url = GetEnv("VENDOR_FEED_URL", "http://vendor-sim:8080/feed");
  config.pg_conninfo = GetEnv("LEGACY_PG_CONNINFO", "");
  config.reports_dir = GetEnv("LEGACY_REPORTS_DIR", "/nfs/reports");
  config.crontab_path = GetEnv("LEGACY_CRONTAB", "/etc/premarket/crontab");

  Status status = GetEnvInt("LEGACY_WORKERS", 4, 1, 64, &config.workers);
  if (!status.ok()) return status;
  int capacity = 0;
  status = GetEnvInt("LEGACY_QUEUE_CAPACITY", 64, 1, 100000, &capacity);
  if (!status.ok()) return status;
  config.queue_capacity = static_cast<std::size_t>(capacity);
  status = GetEnvInt("LEGACY_DEDUP_WINDOW_DAYS", 7, 0, 365,
                     &config.dedup_window_days);
  if (!status.ok()) return status;
  status = GetEnvInt("LEGACY_FETCH_RETRIES", 5, 1, 50, &config.fetch_retries);
  if (!status.ok()) return status;
  return config;
}

bool IsValidDate(const std::string& date) {
  if (date.size() != 10 || date[4] != '-' || date[7] != '-') return false;
  for (std::size_t i = 0; i < date.size(); ++i) {
    if (i == 4 || i == 7) continue;
    if (date[i] < '0' || date[i] > '9') return false;
  }
  const int year = std::stoi(date.substr(0, 4));
  const int month = std::stoi(date.substr(5, 2));
  const int day = std::stoi(date.substr(8, 2));
  static const int kDaysInMonth[] = {31, 28, 31, 30, 31, 30,
                                     31, 31, 30, 31, 30, 31};
  if (year < 1970 || month < 1 || month > 12 || day < 1) return false;
  int max_day = kDaysInMonth[month - 1];
  if (month == 2 && IsLeapYear(year)) max_day = 29;
  return day <= max_day;
}

std::string TodayLocal() {
  time_t now = time(nullptr);
  struct tm local;
  localtime_r(&now, &local);
  char buffer[16];
  strftime(buffer, sizeof(buffer), "%Y-%m-%d", &local);
  return buffer;
}

}  // namespace legacy
}  // namespace premarket
