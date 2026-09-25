// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "db/pg_connection.h"

#include <libpq-fe.h>

#include <cstddef>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace premarket {
namespace legacy {

Status PgConnection::Connect(const std::string& conninfo,
                             std::unique_ptr<PgConnection>* out) {
  PGconn* conn = PQconnectdb(conninfo.c_str());
  if (conn == nullptr) return UnavailableError("PQconnectdb returned null");
  if (PQstatus(conn) != CONNECTION_OK) {
    const std::string message = PQerrorMessage(conn);
    PQfinish(conn);
    return UnavailableError("cannot connect to PostgreSQL: " + message);
  }
  out->reset(new PgConnection(conn));
  return OkStatus();
}

PgConnection::~PgConnection() {
  if (conn_ != nullptr) PQfinish(conn_);
}

std::string PgConnection::LastError() const {
  std::string message = PQerrorMessage(conn_);
  while (!message.empty() && (message[message.size() - 1] == '\n' ||
                              message[message.size() - 1] == ' ')) {
    message.erase(message.size() - 1);
  }
  return message;
}

Status PgConnection::Exec(const std::string& sql) {
  PgResult result(PQexec(conn_, sql.c_str()));
  const ExecStatusType status = PQresultStatus(result.get());
  if (status != PGRES_COMMAND_OK && status != PGRES_TUPLES_OK) {
    return InternalError("SQL failed: " + LastError());
  }
  return OkStatus();
}

Status PgConnection::ExecParams(const std::string& sql,
                                const std::vector<std::string>& params,
                                PgResult* result) {
  std::vector<const char*> values;
  values.reserve(params.size());
  for (std::size_t i = 0; i < params.size(); ++i) {
    values.push_back(params[i].c_str());
  }
  PgResult local(
      PQexecParams(conn_, sql.c_str(), static_cast<int>(params.size()), nullptr,
                   values.empty() ? nullptr : &values[0], nullptr, nullptr, 0));
  const ExecStatusType status = PQresultStatus(local.get());
  if (status != PGRES_COMMAND_OK && status != PGRES_TUPLES_OK) {
    return InternalError("SQL failed: " + LastError());
  }
  if (result != nullptr) *result = std::move(local);
  return OkStatus();
}

Status PgConnection::CopyIn(const std::string& copy_sql,
                            const std::vector<std::string>& rows) {
  {
    PgResult start(PQexec(conn_, copy_sql.c_str()));
    if (PQresultStatus(start.get()) != PGRES_COPY_IN) {
      return InternalError("COPY did not start: " + LastError());
    }
  }

  std::string copy_error;
  for (std::size_t i = 0; i < rows.size(); ++i) {
    if (PQputCopyData(conn_, rows[i].data(),
                      static_cast<int>(rows[i].size())) != 1) {
      copy_error = "PQputCopyData failed: " + LastError();
      break;
    }
  }
  if (PQputCopyEnd(conn_, copy_error.empty() ? nullptr : "client error") != 1) {
    return InternalError("PQputCopyEnd failed: " + LastError());
  }

  // Drain every result; COPY reports its outcome here.
  Status status;
  while (true) {
    PgResult result(PQgetResult(conn_));
    if (result.get() == nullptr) break;
    if (PQresultStatus(result.get()) != PGRES_COMMAND_OK && status.ok()) {
      status = DataLossError("COPY failed: " + LastError());
    }
  }
  if (!copy_error.empty()) return DataLossError(copy_error);
  return status;
}

}  // namespace legacy
}  // namespace premarket
