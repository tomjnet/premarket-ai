// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Small RAII wrappers around the libpq C API, returning absl::Status.

#ifndef PREMARKET_AI_CPP_INGEST_SRC_DB_PG_CONNECTION_H_
#define PREMARKET_AI_CPP_INGEST_SRC_DB_PG_CONNECTION_H_

#include <libpq-fe.h>

#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <memory>
#include <string>
#include <string_view>

#include "absl/status/status.h"
#include "absl/status/statusor.h"

namespace premarket::ingest {

// Owns a PGresult. Move-only.
class PgResult {
 public:
  PgResult() = default;
  explicit PgResult(PGresult* result) : result_(result) {}
  ~PgResult() { Reset(nullptr); }

  PgResult(PgResult&& other) noexcept : result_(other.result_) {
    other.result_ = nullptr;
  }
  PgResult& operator=(PgResult&& other) noexcept {
    if (this != &other) {
      Reset(other.result_);
      other.result_ = nullptr;
    }
    return *this;
  }
  PgResult(const PgResult&) = delete;
  PgResult& operator=(const PgResult&) = delete;

  void Reset(PGresult* result) {
    if (result_ != nullptr) PQclear(result_);
    result_ = result;
  }

  PGresult* get() const { return result_; }
  int rows() const { return result_ == nullptr ? 0 : PQntuples(result_); }
  bool IsNull(int row, int col) const {
    return PQgetisnull(result_, row, col) == 1;
  }
  // A view into the result; valid while this PgResult lives.
  std::string_view Get(int row, int col) const {
    return {PQgetvalue(result_, row, col),
            static_cast<std::size_t>(PQgetlength(result_, row, col))};
  }
  int64_t GetInt64(int row, int col) const;

 private:
  PGresult* result_ = nullptr;
};

// Owns a PGconn. Not thread safe: one connection per thread.
class PgConnection {
 public:
  // Connects with `conninfo`; an empty string uses the PG* environment
  // variables (PGHOST, PGUSER, PGPASSWORD, PGDATABASE, ...).
  static absl::StatusOr<std::unique_ptr<PgConnection>> Connect(
      const std::string& conninfo);

  ~PgConnection();
  PgConnection(const PgConnection&) = delete;
  PgConnection& operator=(const PgConnection&) = delete;

  // Runs one or more statements with no parameters.
  absl::Status Exec(const std::string& sql);

  // Runs a parameterized statement ($1, $2, ...) with text parameters.
  // `result` may be null when rows are not needed.
  absl::Status ExecParams(const std::string& sql,
                          std::initializer_list<std::string> params,
                          PgResult* result);

  // Streams already-formatted COPY text through `copy_sql`
  // (COPY ... FROM STDIN), in chunks.
  absl::Status CopyIn(std::string_view copy_sql, std::string_view data);

 private:
  explicit PgConnection(PGconn* conn) : conn_(conn) {}

  std::string LastError() const;

  PGconn* conn_;
};

}  // namespace premarket::ingest

#endif  // PREMARKET_AI_CPP_INGEST_SRC_DB_PG_CONNECTION_H_
