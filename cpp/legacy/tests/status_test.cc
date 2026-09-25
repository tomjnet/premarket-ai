// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "common/status.h"

#include <string>

#include "gtest/gtest.h"

namespace premarket {
namespace legacy {
namespace {

TEST(StatusTest, DefaultIsOk) {
  Status status;
  EXPECT_TRUE(status.ok());
  EXPECT_EQ(status.ToString(), "OK");
}

TEST(StatusTest, ErrorCarriesCodeAndMessage) {
  Status status = InvalidArgumentError("bad date");
  EXPECT_FALSE(status.ok());
  EXPECT_EQ(status.code(), StatusCode::kInvalidArgument);
  EXPECT_EQ(status.message(), "bad date");
  EXPECT_EQ(status.ToString(), "INVALID_ARGUMENT: bad date");
}

TEST(StatusTest, CodeNames) {
  EXPECT_STREQ(StatusCodeName(StatusCode::kNotFound), "NOT_FOUND");
  EXPECT_STREQ(StatusCodeName(StatusCode::kInternal), "INTERNAL");
  EXPECT_STREQ(StatusCodeName(StatusCode::kUnavailable), "UNAVAILABLE");
  EXPECT_STREQ(StatusCodeName(StatusCode::kDataLoss), "DATA_LOSS");
}

StatusOr<int> Half(int value) {
  if (value % 2 != 0) return InvalidArgumentError("odd");
  return value / 2;
}

TEST(StatusOrTest, HoldsValue) {
  StatusOr<int> result = Half(10);
  ASSERT_TRUE(result.ok());
  EXPECT_EQ(result.value(), 5);
  *result.mutable_value() = 7;
  EXPECT_EQ(result.value(), 7);
}

TEST(StatusOrTest, HoldsError) {
  StatusOr<int> result = Half(3);
  EXPECT_FALSE(result.ok());
  EXPECT_EQ(result.status().message(), "odd");
}

TEST(StatusOrTest, WorksWithStrings) {
  StatusOr<std::string> result(std::string("hello"));
  ASSERT_TRUE(result.ok());
  EXPECT_EQ(result.value(), "hello");
}

}  // namespace
}  // namespace legacy
}  // namespace premarket
