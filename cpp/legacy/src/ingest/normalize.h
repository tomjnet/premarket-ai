// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Text normalization and content hashing used for exact-duplicate flagging.

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_INGEST_NORMALIZE_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_INGEST_NORMALIZE_H_

#include <string>

namespace premarket {
namespace legacy {

// ASCII lowercase, every whitespace run collapsed to one space, trimmed.
// Numbers and punctuation are kept.
std::string NormalizeText(const std::string& text);

// Lowercase hex SHA-256 of `data` (OpenSSL libcrypto).
std::string Sha256Hex(const std::string& data);

// SHA-256 of NormalizeText(headline) + "\n" + NormalizeText(body).
std::string ContentHash(const std::string& headline, const std::string& body);

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_INGEST_NORMALIZE_H_
