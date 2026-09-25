// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// The `report` command: renders the day's non-duplicate news to
// <reports_dir>/<date>.pdf (the NFS share traders open before the bell).

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_REPORT_REPORT_GENERATOR_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_REPORT_REPORT_GENERATOR_H_

#include <string>
#include <vector>

#include "common/config.h"
#include "common/status.h"
#include "db/news_repository.h"

namespace premarket {
namespace legacy {

// Path of the report for `feed_date`.
std::string ReportPath(const std::string& reports_dir,
                       const std::string& feed_date);

// Renders `items` to `path` (written to a temp file, then renamed).
Status RenderReport(const std::string& feed_date, const RunSummary& run,
                    const std::vector<ReportItem>& items,
                    const std::string& path);

// Loads the latest DONE run and its items, then renders the PDF.
Status RunReport(const Config& config, const std::string& feed_date);

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_REPORT_REPORT_GENERATOR_H_
