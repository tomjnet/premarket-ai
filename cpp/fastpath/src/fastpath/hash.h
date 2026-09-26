// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Hashes for the duplicate checks: SHA-256 (L1, exact text), SimHash,
// Hamming distance and band keys (L2, near-duplicate text). The spec is
// python/ai-api/src/ai_api/dedup/normalize.py (ref_sha256) and simhash.py.

#ifndef PREMARKET_AI_CPP_FASTPATH_SRC_FASTPATH_HASH_H_
#define PREMARKET_AI_CPP_FASTPATH_SRC_FASTPATH_HASH_H_

#include <array>
#include <cstdint>
#include <string_view>

#include "absl/status/status.h"
#include "absl/status/statusor.h"

namespace premarket::fastpath {

inline constexpr int kHashBits = 64;
inline constexpr int kMaxNgram = 8;

// Lowercase hex SHA-256, without a terminating NUL.
using Sha256Hex = std::array<char, 64>;
// Band keys, lowest bits first; only the first `bands` entries are used.
using BandKeyArray = std::array<uint64_t, kHashBits>;

// Lowercase hex SHA-256 of `data` into `*out`. Returns Internal if OpenSSL
// fails.
absl::Status Sha256(std::string_view data, Sha256Hex* out);

// FNV-1a 64 of `data`, then the MurmurHash3 64-bit finalizer (fmix64).
uint64_t FeatureHash(std::string_view data);

// SimHash of `text`: words are split on ' ' (empty words skipped); every
// run of `ngram` consecutive words, joined by one space, is a feature
// hashed with FeatureHash (fewer words than `ngram`: one feature of all of
// them); bit i is set when more features have bit i set than not. 0 for a
// text without words. The joined features are never built: each is hashed
// incrementally from a fixed ring of word views, so nothing is allocated.
//
// Returns InvalidArgument when `ngram` is outside [1, kMaxNgram].
absl::StatusOr<uint64_t> SimHash64(std::string_view text, int ngram);

// The number of bits in which `a` and `b` differ.
int Hamming(uint64_t a, uint64_t b);

// Cuts `value` into `bands` consecutive slices from the lowest bit up (the
// first 64 % bands slices are one bit wider) and writes each slice's value
// to (*out)[0 .. bands). Two hashes at most `bands - 1` bits apart share at
// least one slice.
//
// Returns InvalidArgument when `bands` is outside [1, kHashBits].
absl::Status BandKeys(uint64_t value, int bands, BandKeyArray* out);

}  // namespace premarket::fastpath

#endif  // PREMARKET_AI_CPP_FASTPATH_SRC_FASTPATH_HASH_H_
