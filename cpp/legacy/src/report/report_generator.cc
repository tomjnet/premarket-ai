// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "report/report_generator.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

#include <cstddef>
#include <memory>
#include <string>
#include <vector>

#include "common/logging.h"
#include "db/pg_connection.h"
#include "report/pdf_writer.h"

namespace premarket {
namespace legacy {
namespace {

const char kVendorName[] = "Acme Market Wire (simulated)";
const char kDisclaimer[] =
    "SIMULATION: synthetic vendor data. Decision support only, not "
    "investment advice.";

Status EnsureDirectory(const std::string& dir) {
  if (mkdir(dir.c_str(), 0755) == 0 || errno == EEXIST) return OkStatus();
  return InternalError("cannot create " + dir + ": " + strerror(errno));
}

std::string MetaLine(const ReportItem& item) {
  std::string line = item.published_et + " ET";
  if (!item.tickers.empty()) line += "   |   " + item.tickers;
  if (!item.companies.empty()) line += "   |   " + item.companies;
  line += "   |   " + item.source_domain;
  return line;
}

}  // namespace

std::string ReportPath(const std::string& reports_dir,
                       const std::string& feed_date) {
  std::string path = reports_dir;
  if (!path.empty() && path[path.size() - 1] != '/') path += '/';
  return path + feed_date + ".pdf";
}

Status RenderReport(const std::string& feed_date, const RunSummary& run,
                    const std::vector<ReportItem>& items,
                    const std::string& path) {
  std::unique_ptr<PdfWriter> pdf;
  Status status = PdfWriter::Create(std::string("premarket-ai legacy report ") +
                                        feed_date + "   |   " + kDisclaimer,
                                    &pdf);
  if (!status.ok()) return status;

  const TextStyle title(true, 20.0f, 0.0f, 4.0f);
  const TextStyle subtitle(false, 10.0f, 0.25f, 2.0f);
  const TextStyle banner(true, 9.0f, 0.0f, 2.0f);
  const TextStyle headline(true, 11.0f, 0.0f, 2.0f);
  const TextStyle meta(false, 7.5f, 0.4f, 3.0f);
  const TextStyle body(false, 9.5f, 0.1f, 4.0f);

  status = pdf->Write("Pre-market News Report", title);
  if (status.ok()) {
    status = pdf->Write(
        "Trading day " + feed_date + "   |   Vendor: " + kVendorName, subtitle);
  }
  if (status.ok()) {
    status = pdf->Write("Ingest run " + std::to_string(run.run_id) +
                            " finished " + run.finished_et +
                            " ET: " + std::to_string(run.rows_received) +
                            " items received, " + std::to_string(run.dups) +
                            " duplicates removed, " +
                            std::to_string(items.size()) + " stories below.",
                        subtitle);
  }
  if (status.ok()) status = pdf->Write(kDisclaimer, banner);
  if (status.ok()) status = pdf->Rule();

  for (std::size_t i = 0; i < items.size() && status.ok(); ++i) {
    status = pdf->Write(items[i].headline, headline);
    if (status.ok()) status = pdf->Write(MetaLine(items[i]), meta);
    if (status.ok()) status = pdf->Write(items[i].body, body);
    if (status.ok()) status = pdf->Rule();
  }
  if (!status.ok()) return status;

  const std::string temp_path = path + ".tmp";
  status = pdf->Save(temp_path);
  if (!status.ok()) return status;
  if (rename(temp_path.c_str(), path.c_str()) != 0) {
    return InternalError("cannot rename " + temp_path + " to " + path + ": " +
                         strerror(errno));
  }
  return OkStatus();
}

Status RunReport(const Config& config, const std::string& feed_date) {
  std::unique_ptr<PgConnection> conn;
  Status status = PgConnection::Connect(config.pg_conninfo, &conn);
  if (!status.ok()) return status;
  NewsRepository repo(conn.get());

  StatusOr<RunSummary> run = repo.LatestDoneRun(feed_date);
  if (!run.ok()) return run.status();
  StatusOr<std::vector<ReportItem>> items = repo.LoadReportItems(feed_date);
  if (!items.ok()) return items.status();

  status = EnsureDirectory(config.reports_dir);
  if (!status.ok()) return status;
  const std::string path = ReportPath(config.reports_dir, feed_date);
  status = RenderReport(feed_date, run.value(), items.value(), path);
  if (!status.ok()) return status;
  LogInfo("wrote " + path + " with " + std::to_string(items.value().size()) +
          " stories (" + std::to_string(run.value().dups) +
          " duplicates skipped)");
  return OkStatus();
}

}  // namespace legacy
}  // namespace premarket
