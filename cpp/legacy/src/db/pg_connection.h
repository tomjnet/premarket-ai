// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Small RAII wrappers around the libpq C API.

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_DB_PG_CONNECTION_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_DB_PG_CONNECTION_H_

#include <libpq-fe.h>

#include <cstddef>
#include <memory>
#include <string>
#include <vector>

#include "common/status.h"

namespace premarket {
namespace legacy {

// Owns a PGresult. Move-only.
class PgResult {
 public:
  PgResult() : result_(nullptr) {}
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
  std::string Get(int row, int col) const {
    return std::string(
        PQgetvalue(result_, row, col),
        static_cast<std::size_t>(PQgetlength(result_, row, col)));
  }

 private:
  PGresult* result_;
};

// Owns a PGconn. Not thread safe: one connection per thread.
class PgConnection {
 public:
  // Connects with `conninfo`; an empty string uses the PG* environment
  // variables (PGHOST, PGUSER, PGPASSWORD, PGDATABASE, ...).
  static Status Connect(const std::string& conninfo,
                        std::unique_ptr<PgConnection>* out);

  ~PgConnection();
  PgConnection(const PgConnection&) = delete;
  PgConnection& operator=(const PgConnection&) = delete;

  // Runs a statement with no parameters and no result rows.
  Status Exec(const std::string& sql);

  // Runs a parameterized statement ($1, $2, ...) with text parameters.
  // `result` may be null when rows are not needed.
  Status ExecParams(const std::string& sql,
                    const std::vector<std::string>& params, PgResult* result);

  // Streams already-formatted rows through `copy_sql` (COPY ... FROM STDIN).
  Status CopyIn(const std::string& copy_sql,
                const std::vector<std::string>& rows);

 private:
  explicit PgConnection(PGconn* conn) : conn_(conn) {}

  std::string LastError() const;

  PGconn* conn_;
};

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_DB_PG_CONNECTION_H_
