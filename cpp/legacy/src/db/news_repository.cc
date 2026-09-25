// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "db/news_repository.h"

#include <stdlib.h>

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "db/copy_format.h"

namespace premarket {
namespace legacy {
namespace {

int64_t ToInt64(const std::string& text) {
  return strtoll(text.c_str(), nullptr, 10);
}

}  // namespace

StatusOr<int64_t> NewsRepository::StartRun(const std::string& feed_date,
                                           int workers) {
  PgResult result;
  std::vector<std::string> params;
  params.push_back(feed_date);
  params.push_back(std::to_string(workers));
  Status status = conn_->ExecParams(
      "INSERT INTO legacy.ingest_run (feed_date, workers) "
      "VALUES ($1::date, $2::int) RETURNING run_id",
      params, &result);
  if (!status.ok()) return status;
  if (result.rows() != 1) return InternalError("INSERT returned no run_id");
  return ToInt64(result.Get(0, 0));
}

Status NewsRepository::FinishRun(int64_t run_id, const RunStats& stats) {
  std::vector<std::string> params;
  params.push_back(std::to_string(run_id));
  params.push_back(std::to_string(stats.rows_received));
  params.push_back(std::to_string(stats.rows_inserted));
  params.push_back(std::to_string(stats.dups));
  params.push_back(std::to_string(stats.latency.p50_us));
  params.push_back(std::to_string(stats.latency.p99_us));
  params.push_back(std::to_string(stats.latency.p999_us));
  params.push_back(std::to_string(stats.total_ms));
  return conn_->ExecParams(
      "UPDATE legacy.ingest_run SET status = 'DONE', finished_at = now(), "
      "rows_received = $2::int, rows_inserted = $3::int, dups = $4::int, "
      "p50_us = $5::bigint, p99_us = $6::bigint, p999_us = $7::bigint, "
      "total_ms = $8::bigint WHERE run_id = $1::bigint",
      params, nullptr);
}

Status NewsRepository::FailRun(int64_t run_id, const std::string& error) {
  std::vector<std::string> params;
  params.push_back(std::to_string(run_id));
  params.push_back(error);
  return conn_->ExecParams(
      "UPDATE legacy.ingest_run SET status = 'FAILED', finished_at = now(), "
      "error = $2 WHERE run_id = $1::bigint",
      params, nullptr);
}

StatusOr<std::map<std::string, std::string>> NewsRepository::LoadRecentHashes(
    const std::string& feed_date, int window_days) {
  PgResult result;
  std::vector<std::string> params;
  params.push_back(feed_date);
  params.push_back(std::to_string(window_days));
  Status status = conn_->ExecParams(
      "SELECT DISTINCT ON (content_hash) content_hash, vendor_item_id "
      "FROM legacy.vendor_news_raw "
      "WHERE feed_date < $1::date AND feed_date >= $1::date - $2::int "
      "ORDER BY content_hash, feed_date, vendor_item_id",
      params, &result);
  if (!status.ok()) return status;
  std::map<std::string, std::string> hashes;
  for (int row = 0; row < result.rows(); ++row) {
    hashes[result.Get(row, 0)] = result.Get(row, 1);
  }
  return hashes;
}

Status NewsRepository::ReplaceDay(int64_t run_id, const std::string& feed_date,
                                  const std::vector<NewsItem>& items) {
  std::vector<std::string> rows;
  rows.reserve(items.size());
  for (std::size_t i = 0; i < items.size(); ++i) {
    rows.push_back(FormatCopyRow(run_id, feed_date, items[i]));
  }

  Status status = conn_->Exec("BEGIN");
  if (!status.ok()) return status;
  std::vector<std::string> params;
  params.push_back(feed_date);
  status = conn_->ExecParams(
      "DELETE FROM legacy.vendor_news_raw WHERE feed_date = $1::date", params,
      nullptr);
  if (status.ok()) status = conn_->CopyIn(kVendorNewsCopySql, rows);
  if (status.ok()) status = conn_->Exec("COMMIT");
  if (!status.ok()) {
    // Keep the original error; a failed ROLLBACK changes nothing for us.
    conn_->Exec("ROLLBACK");
    return status;
  }
  return OkStatus();
}

StatusOr<RunSummary> NewsRepository::LatestDoneRun(
    const std::string& feed_date) {
  PgResult result;
  std::vector<std::string> params;
  params.push_back(feed_date);
  Status status = conn_->ExecParams(
      "SELECT run_id, "
      "to_char(finished_at AT TIME ZONE 'America/New_York', "
      "'YYYY-MM-DD HH24:MI'), rows_received, dups, coalesce(p99_us, 0) "
      "FROM legacy.ingest_run WHERE feed_date = $1::date AND status = 'DONE' "
      "ORDER BY finished_at DESC LIMIT 1",
      params, &result);
  if (!status.ok()) return status;
  if (result.rows() == 0) {
    return NotFoundError("no DONE ingest run for " + feed_date +
                         "; run 'ingest' first");
  }
  RunSummary summary;
  summary.run_id = ToInt64(result.Get(0, 0));
  summary.finished_et = result.Get(0, 1);
  summary.rows_received = static_cast<int>(ToInt64(result.Get(0, 2)));
  summary.dups = static_cast<int>(ToInt64(result.Get(0, 3)));
  summary.p99_us = ToInt64(result.Get(0, 4));
  return summary;
}

StatusOr<std::vector<ReportItem>> NewsRepository::LoadReportItems(
    const std::string& feed_date) {
  PgResult result;
  std::vector<std::string> params;
  params.push_back(feed_date);
  Status status = conn_->ExecParams(
      "SELECT n.headline, n.body, n.source_domain, "
      "to_char(n.published_at AT TIME ZONE 'America/New_York', 'HH24:MI'), "
      "array_to_string(n.tickers, ', '), "
      "coalesce(string_agg(c.name, ', ' ORDER BY c.name), '') "
      "FROM legacy.vendor_news_raw n "
      "LEFT JOIN legacy.companies c ON c.ticker = ANY (n.tickers) "
      "WHERE n.feed_date = $1::date AND NOT n.is_dup "
      "GROUP BY n.id "
      "ORDER BY n.published_at DESC, n.id",
      params, &result);
  if (!status.ok()) return status;
  std::vector<ReportItem> items;
  items.reserve(static_cast<std::size_t>(result.rows()));
  for (int row = 0; row < result.rows(); ++row) {
    ReportItem item;
    item.headline = result.Get(row, 0);
    item.body = result.Get(row, 1);
    item.source_domain = result.Get(row, 2);
    item.published_et = result.Get(row, 3);
    item.tickers = result.Get(row, 4);
    item.companies = result.Get(row, 5);
    items.push_back(item);
  }
  return items;
}

}  // namespace legacy
}  // namespace premarket
