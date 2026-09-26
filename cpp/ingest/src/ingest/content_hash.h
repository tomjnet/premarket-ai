// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Text normalization and content hashing for exact-duplicate flagging.
// Byte-for-byte the same result as legacy's ContentHash(): lowercase hex
// SHA-256 of NormalizeText(headline) + "\n" + NormalizeText(body).
//
// ContentHasher is the hot-path version: it normalizes into a fixed chunk
// buffer that is streamed into one reused OpenSSL EVP_MD_CTX, so hashing an
// item never allocates. The std::string helpers are for tests and tools.

#ifndef PREMARKET_AI_CPP_INGEST_SRC_INGEST_CONTENT_HASH_H_
#define PREMARKET_AI_CPP_INGEST_SRC_INGEST_CONTENT_HASH_H_

#include <openssl/evp.h>

#include <array>
#include <cstddef>
#include <memory>
#include <span>
#include <string>
#include <string_view>

#include "absl/status/statusor.h"
#include "ingest/news_item.h"

namespace premarket::ingest {

// ASCII lowercase, every run of " \t\n\r\f\v" collapsed to one space,
// trimmed. Numbers, punctuation and non-ASCII bytes are kept.
std::string NormalizeText(std::string_view text);

// Lowercase hex SHA-256 of `data`.
std::string Sha256Hex(std::string_view data);

// SHA-256 of NormalizeText(headline) + "\n" + NormalizeText(body).
// Empty on an OpenSSL failure.
std::string ContentHash(std::string_view headline, std::string_view body);

// One per worker thread. Not thread safe.
class ContentHasher {
 public:
  // Fetches the SHA-256 implementation and allocates the digest context.
  static absl::StatusOr<std::unique_ptr<ContentHasher>> Create();
  ~ContentHasher();

  ContentHasher(const ContentHasher&) = delete;
  ContentHasher& operator=(const ContentHasher&) = delete;

  // Writes the 64 hex digits plus a NUL into `out`. Returns false if
  // OpenSSL fails. No allocation.
  bool Hash(std::string_view headline, std::string_view body,
            std::span<char, kContentHashSize> out);

 private:
  static constexpr std::size_t kChunkSize = 4096;

  ContentHasher(EVP_MD* md, EVP_MD_CTX* ctx) : md_(md), ctx_(ctx) {}

  void Normalize(std::string_view text);
  void Put(char c) {
    chunk_[used_++] = c;
    if (used_ == kChunkSize) Flush();
  }
  void Flush();

  EVP_MD* md_;
  EVP_MD_CTX* ctx_;
  bool update_ok_ = true;
  std::size_t used_ = 0;
  std::array<char, kChunkSize> chunk_{};
};

}  // namespace premarket::ingest

#endif  // PREMARKET_AI_CPP_INGEST_SRC_INGEST_CONTENT_HASH_H_
