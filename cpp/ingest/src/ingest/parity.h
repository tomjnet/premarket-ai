// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// The `parity` command: the strangler-fig check that the C++20 ingester
// stores exactly what the C++11 legacy ingester stores. Waits until both
// runs for the day are DONE, compares legacy.vendor_news_raw with
// ingest.vendor_news_raw column by column in one SQL FULL OUTER JOIN, and
// records the result in ingest.parity_run.

#ifndef PREMARKET_AI_CPP_INGEST_SRC_INGEST_PARITY_H_
#define PREMARKET_AI_CPP_INGEST_SRC_INGEST_PARITY_H_

#include <string>

#include "absl/status/status.h"
#include "common/config.h"

namespace premarket::ingest {

// Returns OK on PASS (zero differences). A FAIL is recorded and returned
// as FAILED_PRECONDITION; a FAILED or missing run is an error.
absl::Status RunParity(const Config& config, const std::string& feed_date);

}  // namespace premarket::ingest

#endif  // PREMARKET_AI_CPP_INGEST_SRC_INGEST_PARITY_H_
