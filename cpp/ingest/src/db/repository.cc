// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "db/repository.h"

#include <array>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
#include <span>
#include <string>

#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "absl/strings/str_cat.h"
#include "db/copy_format.h"

namespace premarket::ingest {
namespace {

// Arbitrary key for pg_advisory_xact_lock: "ingest schema".
constexpr int64_t kSchemaLockKey = 0x70726D6B'00000003;

absl::StatusOr<std::string> ReadFile(const std::string& path) {
  struct Closer {
    void operator()(std::FILE* f) const { std::fclose(f); }
  };
  const std::unique_ptr<std::FILE, Closer> f(std::fopen(path.c_str(), "rb"));
  if (f == nullptr) {
    return absl::NotFoundError(
        absl::StrCat("cannot open schema file ", path,
                     " (INGEST_SCHEMA_FILE): ", std::strerror(errno)));
  }
  std::string text;
  std::array<char, 4096> chunk{};
  std::size_t read = 0;
  while ((read = std::fread(chunk.data(), 1, chunk.size(), f.get())) > 0) {
    text.append(chunk.data(), read);
  }
  if (std::ferror(f.get()) != 0) {
    return absl::DataLossError(absl::StrCat("cannot read ", path));
  }
  return text;
}

}  // namespace

absl::Status ApplySchemaFile(const std::string& path, PgConnection* conn) {
  absl::StatusOr<std::string> sql = ReadFile(path);
  if (!sql.ok()) return sql.status();
  absl::Status status = conn->Exec("BEGIN");
  if (!status.ok()) return status;
  status = conn->Exec(
      absl::StrCat("SELECT pg_advisory_xact_lock(", kSchemaLockKey, ")"));
  if (status.ok()) status = conn->Exec(*sql);
  if (status.ok()) status = conn->Exec("COMMIT");
  if (!status.ok()) {
    conn->Exec("ROLLBACK").IgnoreError();
    return {status.code(), absl::StrCat(path, ": ", status.message())};
  }
  return absl::OkStatus();
}

absl::StatusOr<int64_t> Repository::StartRun(const std::string& feed_date,
                                             int workers) {
  PgResult result;
  absl::Status status = conn_->ExecParams(
      "INSERT INTO ingest.ingest_run (feed_date, workers) "
      "VALUES ($1::date, $2::int) RETURNING run_id",
      {feed_date, absl::StrCat(workers)}, &result);
  if (!status.ok()) return status;
  if (result.rows() != 1) {
    return absl::InternalError("INSERT returned no run_id");
  }
  return result.GetInt64(0, 0);
}

absl::Status Repository::FinishRun(int64_t run_id, const RunStats& stats) {
  return conn_->ExecParams(
      "UPDATE ingest.ingest_run SET status = 'DONE', finished_at = now(), "
      "rows_received = $2::int, rows_inserted = $3::int, dups = $4::int, "
      "p50_us = $5::bigint, p99_us = $6::bigint, p999_us = $7::bigint, "
      "total_ms = $8::bigint, wait_p50_us = $9::bigint, "
      "wait_p99_us = $10::bigint, wait_p999_us = $11::bigint, "
      "fetch_ms = $12::bigint, parse_us = $13::bigint, "
      "dedup_us = $14::bigint, copy_ms = $15::bigint "
      "WHERE run_id = $1::bigint",
      {absl::StrCat(run_id), absl::StrCat(stats.rows_received),
       absl::StrCat(stats.rows_inserted), absl::StrCat(stats.dups),
       absl::StrCat(stats.process_us.p50), absl::StrCat(stats.process_us.p99),
       absl::StrCat(stats.process_us.p999), absl::StrCat(stats.total_ms),
       absl::StrCat(stats.wait_us.p50), absl::StrCat(stats.wait_us.p99),
       absl::StrCat(stats.wait_us.p999), absl::StrCat(stats.fetch_ms),
       absl::StrCat(stats.parse_us), absl::StrCat(stats.dedup_us),
       absl::StrCat(stats.copy_ms)},
      nullptr);
}

absl::Status Repository::FailRun(int64_t run_id, const std::string& error) {
  return conn_->ExecParams(
      "UPDATE ingest.ingest_run SET status = 'FAILED', finished_at = now(), "
      "error = $2 WHERE run_id = $1::bigint",
      {absl::StrCat(run_id), error}, nullptr);
}

absl::Status Repository::LoadRecentHashes(const std::string& feed_date,
                                          int window_days, PgResult* storage,
                                          HashIndex* seen) {
  absl::Status status = conn_->ExecParams(
      "SELECT DISTINCT ON (content_hash) content_hash, vendor_item_id "
      "FROM ingest.vendor_news_raw "
      "WHERE feed_date < $1::date AND feed_date >= $1::date - $2::int "
      "ORDER BY content_hash, feed_date, vendor_item_id",
      {feed_date, absl::StrCat(window_days)}, storage);
  if (!status.ok()) return status;
  seen->reserve(seen->size() + static_cast<std::size_t>(storage->rows()));
  for (int row = 0; row < storage->rows(); ++row) {
    seen->insert_or_assign(storage->Get(row, 0), storage->Get(row, 1));
  }
  return absl::OkStatus();
}

absl::Status Repository::ReplaceDay(int64_t run_id,
                                    const std::string& feed_date,
                                    std::span<const NewsItem> items,
                                    std::string* buffer) {
  buffer->clear();
  for (const NewsItem& item : items) {
    AppendCopyRow(run_id, feed_date, item, buffer);
  }

  absl::Status status = conn_->Exec("BEGIN");
  if (!status.ok()) return status;
  status = conn_->ExecParams(
      "DELETE FROM ingest.vendor_news_raw WHERE feed_date = $1::date",
      {feed_date}, nullptr);
  if (status.ok()) status = conn_->CopyIn(kVendorNewsCopySql, *buffer);
  if (status.ok()) status = conn_->Exec("COMMIT");
  if (!status.ok()) {
    // Keep the original error; a failed ROLLBACK changes nothing for us.
    conn_->Exec("ROLLBACK").IgnoreError();
    return status;
  }
  return absl::OkStatus();
}

}  // namespace premarket::ingest
