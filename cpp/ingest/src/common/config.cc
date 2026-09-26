// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "common/config.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <ctime>
#include <string>
#include <string_view>

#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "absl/strings/numbers.h"
#include "absl/strings/str_cat.h"

namespace premarket::ingest {
namespace {

std::string GetEnv(const char* name, const char* fallback) {
  const char* value = std::getenv(name);
  return (value != nullptr && value[0] != '\0') ? value : fallback;
}

// Parses a base-10 integer in [min_value, max_value].
absl::StatusOr<int64_t> GetEnvInt(const char* name, int64_t fallback,
                                  int64_t min_value, int64_t max_value) {
  const std::string text = GetEnv(name, "");
  if (text.empty()) return fallback;
  int64_t parsed = 0;
  if (!absl::SimpleAtoi(text, &parsed) || parsed < min_value ||
      parsed > max_value) {
    return absl::InvalidArgumentError(
        absl::StrCat(name, " must be an integer in [", min_value, ", ",
                     max_value, "], got '", text, "'"));
  }
  return parsed;
}

bool IsLeapYear(int year) {
  return (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
}

// Digits of `text` as a number; the caller checked they are all digits.
int Digits(std::string_view text) {
  int value = 0;
  for (const char c : text) value = value * 10 + (c - '0');
  return value;
}

}  // namespace

absl::StatusOr<Config> LoadConfigFromEnv() {
  Config config{
      .feed_url = GetEnv("VENDOR_FEED_URL", "http://vendor-sim:8080/feed"),
      .pg_conninfo = GetEnv("INGEST_PG_CONNINFO", ""),
      .schema_file =
          GetEnv("INGEST_SCHEMA_FILE", "/etc/premarket/ingest-schema.sql"),
      .crontab_path = GetEnv("INGEST_CRONTAB", "/etc/premarket/crontab"),
  };

  absl::StatusOr<int64_t> value = GetEnvInt("INGEST_WORKERS", 4, 1, 64);
  if (!value.ok()) return value.status();
  config.workers = static_cast<int>(*value);

  value = GetEnvInt("INGEST_QUEUE_CAPACITY", 64, 1, 1 << 20);
  if (!value.ok()) return value.status();
  // The lock-free ring indexes with a mask; it needs at least two cells.
  config.queue_capacity =
      std::bit_ceil(std::max<std::size_t>(static_cast<std::size_t>(*value), 2));

  value = GetEnvInt("INGEST_DEDUP_WINDOW_DAYS", 7, 0, 365);
  if (!value.ok()) return value.status();
  config.dedup_window_days = static_cast<int>(*value);

  value = GetEnvInt("INGEST_FETCH_RETRIES", 5, 1, 50);
  if (!value.ok()) return value.status();
  config.fetch_retries = static_cast<int>(*value);

  value = GetEnvInt("INGEST_MAX_ITEMS", 4096, 1, 1 << 20);
  if (!value.ok()) return value.status();
  config.max_items = static_cast<std::size_t>(*value);

  value = GetEnvInt("INGEST_MAX_FEED_BYTES", int64_t{64} << 20, 1024,
                    int64_t{1} << 30);
  if (!value.ok()) return value.status();
  config.max_feed_bytes = static_cast<std::size_t>(*value);

  value = GetEnvInt("INGEST_CPU_AFFINITY", 0, 0, 1);
  if (!value.ok()) return value.status();
  config.cpu_affinity = *value == 1;

  value = GetEnvInt("INGEST_PARITY_WAIT_S", 600, 0, 86400);
  if (!value.ok()) return value.status();
  config.parity_wait_s = static_cast<int>(*value);
  return config;
}

bool IsValidDate(std::string_view date) {
  if (date.size() != 10 || date[4] != '-' || date[7] != '-') return false;
  for (std::size_t i = 0; i < date.size(); ++i) {
    if (i == 4 || i == 7) continue;
    if (date[i] < '0' || date[i] > '9') return false;
  }
  const int year = Digits(date.substr(0, 4));
  const int month = Digits(date.substr(5, 2));
  const int day = Digits(date.substr(8, 2));
  static constexpr std::array<int, 12> kDaysInMonth = {31, 28, 31, 30, 31, 30,
                                                       31, 31, 30, 31, 30, 31};
  if (year < 1970 || month < 1 || month > 12 || day < 1) return false;
  int max_day = kDaysInMonth[static_cast<std::size_t>(month - 1)];
  if (month == 2 && IsLeapYear(year)) max_day = 29;
  return day <= max_day;
}

std::string TodayLocal() {
  const time_t now = time(nullptr);
  struct tm local {};
  localtime_r(&now, &local);
  std::array<char, 16> buffer{};
  const std::size_t length =
      strftime(buffer.data(), buffer.size(), "%Y-%m-%d", &local);
  return {buffer.data(), length};
}

}  // namespace premarket::ingest
