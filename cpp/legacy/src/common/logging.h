// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Minimal thread-safe stderr logger: "<UTC time> <LEVEL> <message>".

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_COMMON_LOGGING_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_COMMON_LOGGING_H_

#include <string>

namespace premarket {
namespace legacy {

enum class LogLevel : int { kInfo, kWarning, kError };

void Log(LogLevel level, const std::string& message);

inline void LogInfo(const std::string& message) {
  Log(LogLevel::kInfo, message);
}
inline void LogWarning(const std::string& message) {
  Log(LogLevel::kWarning, message);
}
inline void LogError(const std::string& message) {
  Log(LogLevel::kError, message);
}

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_COMMON_LOGGING_H_
