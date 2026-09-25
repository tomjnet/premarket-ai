// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "common/status.h"

#include <string>

namespace premarket {
namespace legacy {

const char* StatusCodeName(StatusCode code) {
  switch (code) {
    case StatusCode::kOk:
      return "OK";
    case StatusCode::kInvalidArgument:
      return "INVALID_ARGUMENT";
    case StatusCode::kNotFound:
      return "NOT_FOUND";
    case StatusCode::kInternal:
      return "INTERNAL";
    case StatusCode::kUnavailable:
      return "UNAVAILABLE";
    case StatusCode::kDataLoss:
      return "DATA_LOSS";
  }
  return "UNKNOWN";
}

std::string Status::ToString() const {
  if (ok()) return "OK";
  return std::string(StatusCodeName(code_)) + ": " + message_;
}

Status InvalidArgumentError(const std::string& message) {
  return Status(StatusCode::kInvalidArgument, message);
}

Status NotFoundError(const std::string& message) {
  return Status(StatusCode::kNotFound, message);
}

Status InternalError(const std::string& message) {
  return Status(StatusCode::kInternal, message);
}

Status UnavailableError(const std::string& message) {
  return Status(StatusCode::kUnavailable, message);
}

Status DataLossError(const std::string& message) {
  return Status(StatusCode::kDataLoss, message);
}

}  // namespace legacy
}  // namespace premarket
