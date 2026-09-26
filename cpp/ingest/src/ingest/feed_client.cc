// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/feed_client.h"

#include <curl/curl.h>

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <thread>

#include "absl/log/log.h"
#include "absl/status/status.h"
#include "absl/strings/str_cat.h"

namespace premarket::ingest {
namespace {

struct WriteTarget {
  FeedBuffer* buffer;
  bool overflow;
};

std::size_t AppendToBuffer(char* data, std::size_t size, std::size_t count,
                           void* user_data) {
  auto* target = static_cast<WriteTarget*>(user_data);
  const std::size_t bytes = size * count;
  if (!target->buffer->Append(data, bytes)) {
    target->overflow = true;
    return 0;  // aborts the transfer
  }
  return bytes;
}

// Owns a CURL easy handle.
class CurlHandle {
 public:
  CurlHandle() : curl_(curl_easy_init()) {}
  ~CurlHandle() {
    if (curl_ != nullptr) curl_easy_cleanup(curl_);
  }
  CurlHandle(const CurlHandle&) = delete;
  CurlHandle& operator=(const CurlHandle&) = delete;
  CURL* get() const { return curl_; }

 private:
  CURL* curl_;
};

// One attempt. Sets `*retryable` when trying again might help.
absl::Status FetchOnce(const std::string& url, FeedBuffer* out,
                       bool* retryable) {
  *retryable = false;
  CurlHandle handle;
  CURL* curl = handle.get();
  if (curl == nullptr) return absl::InternalError("curl_easy_init failed");

  out->Clear();
  WriteTarget target{.buffer = out, .overflow = false};
  std::array<char, CURL_ERROR_SIZE> error{};
  curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, &AppendToBuffer);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, &target);
  curl_easy_setopt(curl, CURLOPT_ERRORBUFFER, error.data());
  curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
  curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 10L);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, 60L);
  curl_easy_setopt(curl, CURLOPT_USERAGENT, "premarket-ingest/0.1");

  const CURLcode code = curl_easy_perform(curl);
  if (target.overflow) {
    return absl::ResourceExhaustedError(absl::StrCat(
        "GET ", url,
        ": feed is larger than INGEST_MAX_FEED_BYTES=", out->capacity()));
  }
  if (code != CURLE_OK) {
    *retryable = true;
    const std::string_view reason =
        error[0] != '\0' ? error.data() : curl_easy_strerror(code);
    return absl::UnavailableError(
        absl::StrCat("GET ", url, " failed: ", reason));
  }
  long http_status = 0;  // NOLINT: libcurl needs long
  curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_status);
  if (http_status != 200) {
    *retryable = http_status >= 500;
    return absl::UnavailableError(
        absl::StrCat("GET ", url, " returned HTTP ", http_status));
  }
  return absl::OkStatus();
}

}  // namespace

std::string FeedUrlForDate(std::string_view base_url, std::string_view date) {
  const char* separator =
      base_url.find('?') == std::string_view::npos ? "?" : "&";
  return absl::StrCat(base_url, separator, "date=", date);
}

absl::Status FetchUrl(const std::string& url, int attempts, FeedBuffer* out) {
  absl::Status status;
  for (int attempt = 1; attempt <= attempts; ++attempt) {
    bool retryable = false;
    status = FetchOnce(url, out, &retryable);
    if (status.ok()) return status;
    if (!retryable || attempt == attempts) break;
    LOG(WARNING) << status.message() << "; retry " << attempt << "/"
                 << attempts - 1;
    std::this_thread::sleep_for(std::chrono::seconds(2 * attempt));
  }
  return status;
}

}  // namespace premarket::ingest
