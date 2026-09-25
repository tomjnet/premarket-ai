// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Minimal in-house Status / StatusOr<T> for C++11 code. Abseil needs a newer
// standard, so the legacy project keeps its own small version. No exceptions:
// every fallible function returns a Status or a StatusOr<T>.

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_COMMON_STATUS_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_COMMON_STATUS_H_

#include <cassert>
#include <string>
#include <utility>

namespace premarket {
namespace legacy {

enum class StatusCode : int {
  kOk = 0,
  kInvalidArgument = 3,
  kNotFound = 5,
  kInternal = 13,
  kUnavailable = 14,
  kDataLoss = 15,
};

// Returns the canonical name of `code`, for example "INVALID_ARGUMENT".
const char* StatusCodeName(StatusCode code);

class Status {
 public:
  Status() : code_(StatusCode::kOk) {}
  Status(StatusCode code, std::string message)
      : code_(code), message_(std::move(message)) {}

  bool ok() const { return code_ == StatusCode::kOk; }
  StatusCode code() const { return code_; }
  const std::string& message() const { return message_; }

  // "OK" or "<CODE>: <message>".
  std::string ToString() const;

 private:
  StatusCode code_;
  std::string message_;
};

inline Status OkStatus() { return Status(); }
Status InvalidArgumentError(const std::string& message);
Status NotFoundError(const std::string& message);
Status InternalError(const std::string& message);
Status UnavailableError(const std::string& message);
Status DataLossError(const std::string& message);

// Holds either a value or a non-OK Status. T must be default constructible
// (a classic C++11 simplification; no std::optional or unions).
template <typename T>
class StatusOr {
 public:
  // Implicit on purpose, so functions can `return value;` or
  // `return SomeError(...);`.
  StatusOr(const Status& status)  // NOLINT
      : status_(status), value_() {
    assert(!status_.ok());
    if (status_.ok()) {
      status_ = InternalError("StatusOr constructed from an OK status");
    }
  }
  StatusOr(T value)  // NOLINT
      : status_(), value_(std::move(value)) {}

  bool ok() const { return status_.ok(); }
  const Status& status() const { return status_; }

  // Only valid when ok().
  const T& value() const {
    assert(ok());
    return value_;
  }
  T* mutable_value() {
    assert(ok());
    return &value_;
  }

 private:
  Status status_;
  T value_;
};

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_COMMON_STATUS_H_
