// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/content_hash.h"

#include <openssl/evp.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <string_view>

#include "absl/status/status.h"
#include "absl/status/statusor.h"

namespace premarket::ingest {
namespace {

// Byte classes, computed at compile time: one table load per byte instead
// of a chain of comparisons.
constexpr std::array<bool, 256> kIsSpace = [] {
  std::array<bool, 256> table{};
  for (const char c : {' ', '\t', '\n', '\r', '\f', '\v'}) {
    table[static_cast<unsigned char>(c)] = true;
  }
  return table;
}();

constexpr std::array<char, 256> kLower = [] {
  std::array<char, 256> table{};
  for (std::size_t i = 0; i < table.size(); ++i) {
    const auto c = static_cast<char>(static_cast<unsigned char>(i));
    table[i] = (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
  }
  return table;
}();

constexpr std::string_view kHexDigits = "0123456789abcdef";

// Writes 2 * digest.size() hex digits to `out`.
void HexEncode(std::span<const unsigned char> digest, char* out) {
  for (const unsigned char byte : digest) {
    *out++ = kHexDigits[byte >> 4];
    *out++ = kHexDigits[byte & 0x0f];
  }
}

}  // namespace

std::string NormalizeText(std::string_view text) {
  std::string out;
  out.reserve(text.size());
  bool pending_space = false;
  for (const char c : text) {
    if (kIsSpace[static_cast<unsigned char>(c)]) {
      pending_space = !out.empty();
      continue;
    }
    if (pending_space) {
      out.push_back(' ');
      pending_space = false;
    }
    out.push_back(kLower[static_cast<unsigned char>(c)]);
  }
  return out;
}

std::string Sha256Hex(std::string_view data) {
  std::array<unsigned char, EVP_MAX_MD_SIZE> digest{};
  unsigned int length = 0;
  if (EVP_Digest(data.data(), data.size(), digest.data(), &length, EVP_sha256(),
                 nullptr) != 1) {
    return {};
  }
  std::string hex(static_cast<std::size_t>(length) * 2, '\0');
  HexEncode({digest.data(), length}, hex.data());
  return hex;
}

std::string ContentHash(std::string_view headline, std::string_view body) {
  absl::StatusOr<std::unique_ptr<ContentHasher>> hasher =
      ContentHasher::Create();
  if (!hasher.ok()) return {};
  std::array<char, kContentHashSize> out{};
  if (!(*hasher)->Hash(headline, body, out)) return {};
  return {out.data(), kContentHashSize - 1};
}

absl::StatusOr<std::unique_ptr<ContentHasher>> ContentHasher::Create() {
  // An explicit fetch once, instead of an implicit one per digest.
  EVP_MD* md = EVP_MD_fetch(nullptr, "SHA256", nullptr);
  if (md == nullptr) return absl::InternalError("EVP_MD_fetch(SHA256) failed");
  EVP_MD_CTX* ctx = EVP_MD_CTX_new();
  if (ctx == nullptr) {
    EVP_MD_free(md);
    return absl::InternalError("EVP_MD_CTX_new failed");
  }
  return std::unique_ptr<ContentHasher>(new ContentHasher(md, ctx));
}

ContentHasher::~ContentHasher() {
  EVP_MD_CTX_free(ctx_);
  EVP_MD_free(md_);
}

void ContentHasher::Flush() {
  if (used_ > 0 && EVP_DigestUpdate(ctx_, chunk_.data(), used_) != 1) {
    update_ok_ = false;
  }
  used_ = 0;
}

void ContentHasher::Normalize(std::string_view text) {
  bool wrote = false;
  bool pending_space = false;
  for (const char c : text) {
    if (kIsSpace[static_cast<unsigned char>(c)]) {
      pending_space = wrote;
      continue;
    }
    if (pending_space) {
      Put(' ');
      pending_space = false;
    }
    Put(kLower[static_cast<unsigned char>(c)]);
    wrote = true;
  }
}

bool ContentHasher::Hash(std::string_view headline, std::string_view body,
                         std::span<char, kContentHashSize> out) {
  // Reuses the context and its provider state: no allocation.
  if (EVP_DigestInit_ex2(ctx_, md_, nullptr) != 1) return false;
  used_ = 0;
  update_ok_ = true;
  Normalize(headline);
  Put('\n');
  Normalize(body);
  Flush();
  std::array<unsigned char, EVP_MAX_MD_SIZE> digest{};
  unsigned int length = 0;
  if (!update_ok_ || EVP_DigestFinal_ex(ctx_, digest.data(), &length) != 1 ||
      static_cast<std::size_t>(length) * 2 != kContentHashSize - 1) {
    return false;
  }
  HexEncode({digest.data(), length}, out.data());
  out[kContentHashSize - 1] = '\0';
  return true;
}

}  // namespace premarket::ingest
