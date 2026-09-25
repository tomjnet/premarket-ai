// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// premarket-legacy: the C++11 "before" system.
//
//   premarket-legacy ingest [--date=YYYY-MM-DD]   vendor feed -> PostgreSQL
//   premarket-legacy report [--date=YYYY-MM-DD]   PostgreSQL -> PDF on NFS
//   premarket-legacy cron                          run the supercronic schedule
//
// The date defaults to today in the TZ time zone (America/New_York).

#include <curl/curl.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include <string>
#include <vector>

#include "common/config.h"
#include "common/logging.h"
#include "common/status.h"
#include "ingest/ingester.h"
#include "report/report_generator.h"

namespace premarket {
namespace legacy {
namespace {

const char kSupercronic[] = "/usr/local/bin/supercronic";

const char kUsage[] =
    "usage: premarket-legacy <ingest|report|cron> [--date=YYYY-MM-DD]\n"
    "  ingest  fetch the vendor feed and load legacy.vendor_news_raw\n"
    "  report  render <LEGACY_REPORTS_DIR>/<date>.pdf from today's rows\n"
    "  cron    run the schedule in LEGACY_CRONTAB with supercronic\n";

// Parses "--date=X" or "--date X". Returns false on unknown arguments.
bool ParseDate(int argc, char** argv, std::string* date) {
  for (int i = 2; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg.compare(0, 7, "--date=") == 0) {
      *date = arg.substr(7);
    } else if (arg == "--date" && i + 1 < argc) {
      *date = argv[++i];
    } else {
      return false;
    }
  }
  return true;
}

int RunCron(const Config& config) {
  LogInfo("starting supercronic with " + config.crontab_path);
  std::string binary = kSupercronic;
  std::string crontab = config.crontab_path;
  std::vector<char*> args;
  args.push_back(&binary[0]);
  args.push_back(&crontab[0]);
  args.push_back(nullptr);
  execv(kSupercronic, &args[0]);
  LogError(std::string("cannot exec ") + kSupercronic + ": " + strerror(errno));
  return 1;
}

int Main(int argc, char** argv) {
  if (argc < 2 || strcmp(argv[1], "--help") == 0 ||
      strcmp(argv[1], "-h") == 0) {
    fputs(kUsage, argc < 2 ? stderr : stdout);
    return argc < 2 ? 2 : 0;
  }
  const std::string command = argv[1];

  std::string date;
  if (!ParseDate(argc, argv, &date)) {
    fputs(kUsage, stderr);
    return 2;
  }
  if (date.empty()) date = TodayLocal();
  if (!IsValidDate(date)) {
    LogError("invalid --date '" + date + "', expected YYYY-MM-DD");
    return 2;
  }

  StatusOr<Config> config = LoadConfigFromEnv();
  if (!config.ok()) {
    LogError(config.status().ToString());
    return 2;
  }

  Status status;
  if (command == "ingest") {
    if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) {
      LogError("curl_global_init failed");
      return 1;
    }
    status = RunIngest(config.value(), date);
    curl_global_cleanup();
  } else if (command == "report") {
    status = RunReport(config.value(), date);
  } else if (command == "cron") {
    return RunCron(config.value());
  } else {
    fputs(kUsage, stderr);
    return 2;
  }

  if (!status.ok()) {
    LogError(command + " " + date + " failed: " + status.ToString());
    return 1;
  }
  return 0;
}

}  // namespace
}  // namespace legacy
}  // namespace premarket

int main(int argc, char** argv) { return premarket::legacy::Main(argc, argv); }
