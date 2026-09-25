// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/feed_client.h"

#include <curl/curl.h>

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <string>
#include <thread>

#include "common/logging.h"

namespace premarket {
namespace legacy {
namespace {

// Cap on the response size: the feed is ~100 small items.
const std::size_t kMaxResponseBytes = static_cast<std::size_t>(64) << 20;

std::size_t AppendToString(char* data, std::size_t size, std::size_t count,
                           void* user_data) {
  std::string* out = static_cast<std::string*>(user_data);
  const std::size_t bytes = size * count;
  if (out->size() + bytes > kMaxResponseBytes) return 0;  // aborts transfer
  out->append(data, bytes);
  return bytes;
}

// One attempt. Sets `*retryable` when trying again might help.
Status FetchOnce(const std::string& url, std::string* body, bool* retryable) {
  *retryable = false;
  CURL* curl = curl_easy_init();
  if (curl == nullptr) return InternalError("curl_easy_init failed");

  body->clear();
  char error[CURL_ERROR_SIZE];
  error[0] = '\0';
  curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, &AppendToString);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, body);
  curl_easy_setopt(curl, CURLOPT_ERRORBUFFER, error);
  curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
  curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 10L);
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, 60L);
  curl_easy_setopt(curl, CURLOPT_USERAGENT, "premarket-legacy/0.1");

  const CURLcode code = curl_easy_perform(curl);
  int64_t http_status = 0;
  if (code == CURLE_OK) {
    long response_code = 0;  // NOLINT - libcurl requires long
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &response_code);
    http_status = response_code;
  }
  curl_easy_cleanup(curl);

  if (code != CURLE_OK) {
    *retryable = true;
    return UnavailableError(
        "GET " + url + " failed: " +
        (error[0] != '\0' ? std::string(error) : curl_easy_strerror(code)));
  }
  if (http_status != 200) {
    *retryable = http_status >= 500;
    return UnavailableError("GET " + url + " returned HTTP " +
                            std::to_string(http_status));
  }
  return OkStatus();
}

std::string RetryMessage(const Status& status, int attempt, int attempts) {
  return status.message() + "; retry " + std::to_string(attempt) + "/" +
         std::to_string(attempts - 1);
}

}  // namespace

std::string FeedUrlForDate(const std::string& base_url,
                           const std::string& date) {
  const char separator = base_url.find('?') == std::string::npos ? '?' : '&';
  return base_url + separator + "date=" + date;
}

StatusOr<std::string> FetchUrl(const std::string& url, int attempts) {
  std::string body;
  Status status;
  for (int attempt = 1; attempt <= attempts; ++attempt) {
    bool retryable = false;
    status = FetchOnce(url, &body, &retryable);
    if (status.ok()) return body;
    if (!retryable || attempt == attempts) break;
    LogWarning(RetryMessage(status, attempt, attempts));
    std::this_thread::sleep_for(std::chrono::seconds(2 * attempt));
  }
  return status;
}

}  // namespace legacy
}  // namespace premarket
