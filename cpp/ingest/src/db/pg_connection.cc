// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "db/pg_connection.h"

#include <libpq-fe.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <memory>
#include <string>
#include <string_view>
#include <utility>

#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "absl/strings/numbers.h"
#include "absl/strings/str_cat.h"

namespace premarket::ingest {
namespace {

constexpr std::size_t kMaxParams = 16;
// COPY data goes to the server in chunks of this size.
constexpr std::size_t kCopyChunkBytes = std::size_t{1} << 20;

}  // namespace

int64_t PgResult::GetInt64(int row, int col) const {
  int64_t value = 0;
  if (!absl::SimpleAtoi(Get(row, col), &value)) return 0;
  return value;
}

absl::StatusOr<std::unique_ptr<PgConnection>> PgConnection::Connect(
    const std::string& conninfo) {
  PGconn* conn = PQconnectdb(conninfo.c_str());
  if (conn == nullptr) {
    return absl::UnavailableError("PQconnectdb returned null");
  }
  if (PQstatus(conn) != CONNECTION_OK) {
    std::string message = PQerrorMessage(conn);
    PQfinish(conn);
    while (!message.empty() && message.back() == '\n') message.pop_back();
    return absl::UnavailableError(
        absl::StrCat("cannot connect to PostgreSQL: ", message));
  }
  return std::unique_ptr<PgConnection>(new PgConnection(conn));
}

PgConnection::~PgConnection() {
  if (conn_ != nullptr) PQfinish(conn_);
}

std::string PgConnection::LastError() const {
  std::string message = PQerrorMessage(conn_);
  while (!message.empty() &&
         (message.back() == '\n' || message.back() == ' ')) {
    message.pop_back();
  }
  return message;
}

absl::Status PgConnection::Exec(const std::string& sql) {
  const PgResult result(PQexec(conn_, sql.c_str()));
  const ExecStatusType status = PQresultStatus(result.get());
  if (status != PGRES_COMMAND_OK && status != PGRES_TUPLES_OK) {
    return absl::InternalError(absl::StrCat("SQL failed: ", LastError()));
  }
  return absl::OkStatus();
}

absl::Status PgConnection::ExecParams(const std::string& sql,
                                      std::initializer_list<std::string> params,
                                      PgResult* result) {
  if (params.size() > kMaxParams) {
    return absl::InvalidArgumentError("too many SQL parameters");
  }
  std::array<const char*, kMaxParams> values{};
  std::size_t count = 0;
  for (const std::string& param : params) values[count++] = param.c_str();
  PgResult local(PQexecParams(conn_, sql.c_str(), static_cast<int>(count),
                              nullptr, values.data(), nullptr, nullptr, 0));
  const ExecStatusType status = PQresultStatus(local.get());
  if (status != PGRES_COMMAND_OK && status != PGRES_TUPLES_OK) {
    return absl::InternalError(absl::StrCat("SQL failed: ", LastError()));
  }
  if (result != nullptr) *result = std::move(local);
  return absl::OkStatus();
}

absl::Status PgConnection::CopyIn(std::string_view copy_sql,
                                  std::string_view data) {
  {
    const PgResult start(PQexec(conn_, std::string(copy_sql).c_str()));
    if (PQresultStatus(start.get()) != PGRES_COPY_IN) {
      return absl::InternalError(
          absl::StrCat("COPY did not start: ", LastError()));
    }
  }

  std::string copy_error;
  while (!data.empty()) {
    const std::size_t chunk = std::min(data.size(), kCopyChunkBytes);
    if (PQputCopyData(conn_, data.data(), static_cast<int>(chunk)) != 1) {
      copy_error = absl::StrCat("PQputCopyData failed: ", LastError());
      break;
    }
    data.remove_prefix(chunk);
  }
  if (PQputCopyEnd(conn_, copy_error.empty() ? nullptr : "client error") != 1) {
    return absl::InternalError(
        absl::StrCat("PQputCopyEnd failed: ", LastError()));
  }

  // Drain every result; COPY reports its outcome here.
  absl::Status status;
  while (true) {
    const PgResult result(PQgetResult(conn_));
    if (result.get() == nullptr) break;
    if (PQresultStatus(result.get()) != PGRES_COMMAND_OK && status.ok()) {
      status = absl::DataLossError(absl::StrCat("COPY failed: ", LastError()));
    }
  }
  if (!copy_error.empty()) return absl::DataLossError(copy_error);
  return status;
}

}  // namespace premarket::ingest
