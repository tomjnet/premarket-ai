// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// libcurl HTTP GET for the vendor feed.

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_INGEST_FEED_CLIENT_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_INGEST_FEED_CLIENT_H_

#include <string>

#include "common/status.h"

namespace premarket {
namespace legacy {

// Builds "<base_url>?date=<date>".
std::string FeedUrlForDate(const std::string& base_url,
                           const std::string& date);

// GETs `url`. Retries connection errors and HTTP 5xx up to `attempts` times
// with a growing delay. curl_global_init() must have been called.
StatusOr<std::string> FetchUrl(const std::string& url, int attempts);

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_INGEST_FEED_CLIENT_H_
