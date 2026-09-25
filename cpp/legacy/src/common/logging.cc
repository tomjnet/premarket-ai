// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "common/logging.h"

#include <stdio.h>
#include <time.h>

#include <mutex>
#include <string>

namespace premarket {
namespace legacy {
namespace {

std::mutex& LogMutex() {
  static std::mutex* mu = new std::mutex();
  return *mu;
}

const char* LevelName(LogLevel level) {
  switch (level) {
    case LogLevel::kInfo:
      return "INFO";
    case LogLevel::kWarning:
      return "WARN";
    case LogLevel::kError:
      return "ERROR";
  }
  return "?";
}

}  // namespace

void Log(LogLevel level, const std::string& message) {
  time_t now = time(nullptr);
  struct tm utc;
  gmtime_r(&now, &utc);
  char stamp[32];
  strftime(stamp, sizeof(stamp), "%Y-%m-%dT%H:%M:%SZ", &utc);

  std::lock_guard<std::mutex> lock(LogMutex());
  fprintf(stderr, "%s %-5s %s\n", stamp, LevelName(level), message.c_str());
  fflush(stderr);
}

}  // namespace legacy
}  // namespace premarket
