// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/normalize.h"

#include <openssl/evp.h>

#include <cstddef>
#include <string>

namespace premarket {
namespace legacy {
namespace {

bool IsSpace(char c) {
  return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' ||
         c == '\v';
}

char ToLowerAscii(char c) {
  return (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
}

}  // namespace

std::string NormalizeText(const std::string& text) {
  std::string out;
  out.reserve(text.size());
  bool pending_space = false;
  for (std::size_t i = 0; i < text.size(); ++i) {
    const char c = text[i];
    if (IsSpace(c)) {
      pending_space = !out.empty();
      continue;
    }
    if (pending_space) {
      out.push_back(' ');
      pending_space = false;
    }
    out.push_back(ToLowerAscii(c));
  }
  return out;
}

std::string Sha256Hex(const std::string& data) {
  unsigned char digest[EVP_MAX_MD_SIZE];
  unsigned int length = 0;
  if (EVP_Digest(data.data(), data.size(), digest, &length, EVP_sha256(),
                 nullptr) != 1) {
    return std::string();
  }
  static const char kHex[] = "0123456789abcdef";
  std::string hex;
  hex.reserve(static_cast<std::size_t>(length) * 2);
  for (unsigned int i = 0; i < length; ++i) {
    hex.push_back(kHex[digest[i] >> 4]);
    hex.push_back(kHex[digest[i] & 0x0f]);
  }
  return hex;
}

std::string ContentHash(const std::string& headline, const std::string& body) {
  return Sha256Hex(NormalizeText(headline) + "\n" + NormalizeText(body));
}

}  // namespace legacy
}  // namespace premarket
