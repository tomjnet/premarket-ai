// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// premarket-ingest: the C++20 low-latency ingester (shadow of legacy).
//
//   premarket-ingest ingest [--date=YYYY-MM-DD]   vendor feed -> ingest.*
//   premarket-ingest parity [--date=YYYY-MM-DD]   legacy.* vs ingest.* rows
//   premarket-ingest cron                          run the supercronic schedule
//
// The date defaults to today in the TZ time zone (America/New_York).

#include <curl/curl.h>
#include <unistd.h>

#include <array>
#include <cerrno>
#include <cstring>
#include <string>
#include <vector>

#include "absl/flags/flag.h"
#include "absl/flags/parse.h"
#include "absl/flags/usage.h"
#include "absl/log/globals.h"
#include "absl/log/initialize.h"
#include "absl/log/log.h"
#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "common/config.h"
#include "ingest/ingester.h"
#include "ingest/parity.h"

ABSL_FLAG(std::string, date, "",
          "Feed date as YYYY-MM-DD (default: today in TZ)");

namespace premarket::ingest {
namespace {

constinit const char* const kSupercronic = "/usr/local/bin/supercronic";

constinit const char* const kUsage =
    "premarket-ingest <ingest|parity|cron> [--date=YYYY-MM-DD]\n"
    "  ingest  fetch the vendor feed and load ingest.vendor_news_raw\n"
    "  parity  compare legacy.vendor_news_raw with ingest.vendor_news_raw\n"
    "  cron    run the schedule in INGEST_CRONTAB with supercronic";

int RunCron(const Config& config) {
  LOG(INFO) << "starting supercronic with " << config.crontab_path;
  std::string binary = kSupercronic;
  std::string crontab = config.crontab_path;
  std::array<char*, 3> args = {binary.data(), crontab.data(), nullptr};
  execv(kSupercronic, args.data());
  LOG(ERROR) << "cannot exec " << kSupercronic << ": " << std::strerror(errno);
  return 1;
}

int Main(int argc, char** argv) {
  absl::SetProgramUsageMessage(kUsage);
  const std::vector<char*> positional = absl::ParseCommandLine(argc, argv);
  absl::InitializeLog();
  absl::SetStderrThreshold(absl::LogSeverityAtLeast::kInfo);

  if (positional.size() != 2) {
    LOG(ERROR) << "usage: " << kUsage;
    return 2;
  }
  const std::string command = positional[1];

  std::string date = absl::GetFlag(FLAGS_date);
  if (date.empty()) date = TodayLocal();
  if (!IsValidDate(date)) {
    LOG(ERROR) << "invalid --date '" << date << "', expected YYYY-MM-DD";
    return 2;
  }

  const absl::StatusOr<Config> config = LoadConfigFromEnv();
  if (!config.ok()) {
    LOG(ERROR) << config.status();
    return 2;
  }

  absl::Status status;
  if (command == "ingest") {
    if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) {
      LOG(ERROR) << "curl_global_init failed";
      return 1;
    }
    status = RunIngest(*config, date);
    curl_global_cleanup();
  } else if (command == "parity") {
    status = RunParity(*config, date);
  } else if (command == "cron") {
    return RunCron(*config);
  } else {
    LOG(ERROR) << "unknown command '" << command << "'; usage: " << kUsage;
    return 2;
  }

  if (!status.ok()) {
    LOG(ERROR) << command << " " << date << " failed: " << status;
    return 1;
  }
  return 0;
}

}  // namespace
}  // namespace premarket::ingest

int main(int argc, char** argv) { return premarket::ingest::Main(argc, argv); }
