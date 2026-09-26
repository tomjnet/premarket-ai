// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// libcurl HTTP GET for the vendor feed, written straight into the
// preallocated FeedBuffer (no growing string).

#ifndef PREMARKET_AI_CPP_INGEST_SRC_INGEST_FEED_CLIENT_H_
#define PREMARKET_AI_CPP_INGEST_SRC_INGEST_FEED_CLIENT_H_

#include <string>
#include <string_view>

#include "absl/status/status.h"
#include "ingest/feed_parser.h"

namespace premarket::ingest {

// Builds "<base_url>?date=<date>".
std::string FeedUrlForDate(std::string_view base_url, std::string_view date);

// GETs `url` into `out`. Retries connection errors and HTTP 5xx up to
// `attempts` times with a growing delay, like legacy. A body larger than the
// buffer fails without retrying. curl_global_init() must have been called.
absl::Status FetchUrl(const std::string& url, int attempts, FeedBuffer* out);

}  // namespace premarket::ingest

#endif  // PREMARKET_AI_CPP_INGEST_SRC_INGEST_FEED_CLIENT_H_
