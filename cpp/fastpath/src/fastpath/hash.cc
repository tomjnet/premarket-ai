// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "fastpath/hash.h"

#include <openssl/evp.h>

#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <string_view>

#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "absl/strings/str_cat.h"

namespace premarket::fastpath {
namespace {

constexpr uint64_t kFnvOffset = 0xCBF29CE484222325ULL;
constexpr uint64_t kFnvPrime = 0x100000001B3ULL;
constexpr std::string_view kHexDigits = "0123456789abcdef";

uint64_t FnvAppend(uint64_t value, std::string_view data) {
  for (const char c : data) {
    value ^= static_cast<uint8_t>(c);
    value *= kFnvPrime;
  }
  return value;
}

uint64_t Fmix64(uint64_t value) {
  value ^= value >> 33;
  value *= 0xFF51AFD7ED558CCDULL;
  value ^= value >> 33;
  value *= 0xC4CEB9FE1A85EC53ULL;
  value ^= value >> 33;
  return value;
}

// The words of one text, kept in a fixed ring of the last `ngram` words so
// each n-gram is hashed without building the joined string.
class NgramHasher {
 public:
  explicit NgramHasher(int ngram) : ngram_(ngram) {}

  // Adds the next word; once `ngram` words are in, hashes the n-gram that
  // ends with it.
  void AddWord(std::string_view word) {
    ring_[seen_ % ngram_] = word;
    ++seen_;
    if (seen_ >= ngram_) AddFeature(seen_ - ngram_, ngram_);
  }

  // The SimHash; a text with fewer words than `ngram` is one feature.
  uint64_t Finish() {
    if (seen_ == 0) return 0;
    if (seen_ < ngram_) AddFeature(0, static_cast<int>(seen_));
    // Bit i is set when more features have it set than not.
    uint64_t result = 0;
    for (int bit = 0; bit < kHashBits; ++bit) {
      if (2 * ones_[bit] > features_) result |= uint64_t{1} << bit;
    }
    return result;
  }

 private:
  // Hashes the words first .. first + count - 1 joined by single spaces.
  void AddFeature(int64_t first, int count) {
    uint64_t value = kFnvOffset;
    for (int k = 0; k < count; ++k) {
      if (k != 0) value = FnvAppend(value, " ");
      value = FnvAppend(value, ring_[(first + k) % ngram_]);
    }
    value = Fmix64(value);
    // Branch-free, so the compiler vectorizes it.
    for (int bit = 0; bit < kHashBits; ++bit) {
      ones_[bit] += static_cast<int64_t>((value >> bit) & 1U);
    }
    ++features_;
  }

  const int ngram_;
  int64_t seen_ = 0;
  std::array<std::string_view, kMaxNgram> ring_{};
  int64_t features_ = 0;
  // Per bit, the number of features with that bit set.
  std::array<int64_t, kHashBits> ones_{};
};

}  // namespace

absl::Status Sha256(std::string_view data, Sha256Hex* out) {
  std::array<unsigned char, EVP_MAX_MD_SIZE> digest{};
  unsigned int length = 0;
  if (EVP_Digest(data.data(), data.size(), digest.data(), &length, EVP_sha256(),
                 nullptr) != 1 ||
      static_cast<size_t>(length) * 2 != out->size()) {
    return absl::InternalError("OpenSSL SHA-256 failed");
  }
  for (size_t i = 0; i < length; ++i) {
    (*out)[2 * i] = kHexDigits[digest[i] >> 4];
    (*out)[(2 * i) + 1] = kHexDigits[digest[i] & 0x0F];
  }
  return absl::OkStatus();
}

uint64_t FeatureHash(std::string_view data) {
  return Fmix64(FnvAppend(kFnvOffset, data));
}

absl::StatusOr<uint64_t> SimHash64(std::string_view text, int ngram) {
  if (ngram < 1 || ngram > kMaxNgram) {
    return absl::InvalidArgumentError(
        absl::StrCat("ngram must be in [1, ", kMaxNgram, "], got ", ngram));
  }
  NgramHasher hasher(ngram);
  size_t start = 0;
  while (start < text.size()) {
    size_t end = text.find(' ', start);
    if (end == std::string_view::npos) end = text.size();
    if (end > start) hasher.AddWord(text.substr(start, end - start));
    start = end + 1;
  }
  return hasher.Finish();
}

int Hamming(uint64_t a, uint64_t b) { return std::popcount(a ^ b); }

absl::Status BandKeys(uint64_t value, int bands, BandKeyArray* out) {
  if (bands < 1 || bands > kHashBits) {
    return absl::InvalidArgumentError(
        absl::StrCat("bands must be in [1, ", kHashBits, "], got ", bands));
  }
  const int base = kHashBits / bands;
  const int extra = kHashBits % bands;
  int shift = 0;
  for (int i = 0; i < bands; ++i) {
    const int width = base + (i < extra ? 1 : 0);
    const uint64_t mask =
        width == kHashBits ? ~uint64_t{0} : (uint64_t{1} << width) - 1;
    (*out)[i] = (value >> shift) & mask;
    shift += width;
  }
  return absl::OkStatus();
}

}  // namespace premarket::fastpath
