// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Expected values come from the Python reference (ref_sha256 in
// normalize.py; ref_feature_hash, ref_simhash64, ref_band_keys in
// simhash.py, python/ai-api/src/ai_api/dedup).

#include "fastpath/hash.h"

#include <cstdint>
#include <string>
#include <string_view>

#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "gtest/gtest.h"

namespace premarket::fastpath {
namespace {

std::string Sha256String(std::string_view data) {
  Sha256Hex hex;
  EXPECT_TRUE(Sha256(data, &hex).ok());
  return {hex.data(), hex.size()};
}

uint64_t SimHash(std::string_view text, int ngram) {
  const absl::StatusOr<uint64_t> value = SimHash64(text, ngram);
  EXPECT_TRUE(value.ok()) << value.status();
  return value.value_or(0);
}

TEST(Sha256Test, KnownDigests) {
  EXPECT_EQ(Sha256String(""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  EXPECT_EQ(Sha256String("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
}

TEST(FeatureHashTest, FnvThenFmix) {
  EXPECT_EQ(FeatureHash(""), 0xEFD01F60BA992926ULL);
  EXPECT_EQ(FeatureHash("a"), 0x82A2A958A9BECE5BULL);
  EXPECT_EQ(FeatureHash("a b"), 0x53CA607C98C45326ULL);
}

TEST(SimHash64Test, NoWordsIsZero) {
  EXPECT_EQ(SimHash("", 2), 0U);
  EXPECT_EQ(SimHash("   ", 1), 0U);
}

TEST(SimHash64Test, FewerWordsThanNgramIsOneFeature) {
  EXPECT_EQ(SimHash("a", 2), FeatureHash("a"));
  EXPECT_EQ(SimHash("a b", 2), FeatureHash("a b"));
  EXPECT_EQ(SimHash("a b c", 8), 0x21A3B3FE9EE4787AULL);
  EXPECT_EQ(SimHash("a b c", 8), FeatureHash("a b c"));
}

TEST(SimHash64Test, EmptyWordsAreSkipped) {
  EXPECT_EQ(SimHash("  a   b  ", 2), 0x53CA607C98C45326ULL);
}

TEST(SimHash64Test, NgramFeatures) {
  EXPECT_EQ(SimHash("a b c", 1), 0x66233358F2DAC25AULL);
  EXPECT_EQ(SimHash("a b c", 2), 0x02CA202818C00102ULL);
  EXPECT_EQ(SimHash("rose 12% $3.5", 3), 0x4FCF221061BF7DADULL);
}

TEST(SimHash64Test, RejectsBadNgram) {
  EXPECT_TRUE(absl::IsInvalidArgument(SimHash64("a b", 0).status()));
  EXPECT_TRUE(absl::IsInvalidArgument(SimHash64("a b", 9).status()));
  EXPECT_TRUE(absl::IsInvalidArgument(SimHash64("a b", -1).status()));
}

TEST(HammingTest, CountsDifferingBits) {
  EXPECT_EQ(Hamming(0, 0), 0);
  EXPECT_EQ(Hamming(0, ~uint64_t{0}), 64);
  EXPECT_EQ(Hamming(0b1011, 0b0110), 3);
}

TEST(BandKeysTest, UnevenBandsAreWiderFirst) {
  BandKeyArray keys{};
  ASSERT_TRUE(BandKeys(0x0123456789ABCDEFULL, 3, &keys).ok());
  // Widths 22, 21, 21.
  EXPECT_EQ(keys[0], 2870767U);
  EXPECT_EQ(keys[1], 1416742U);
  EXPECT_EQ(keys[2], 9320U);
  ASSERT_TRUE(BandKeys(0x0123456789ABCDEFULL, 5, &keys).ok());
  // Widths 13, 13, 13, 13, 12.
  EXPECT_EQ(keys[0], 0xDEFU);
  EXPECT_EQ(keys[1], 0xD5EU);
  EXPECT_EQ(keys[2], 0x19E2U);
  EXPECT_EQ(keys[3], 0x68AU);
  EXPECT_EQ(keys[4], 0x12U);
}

TEST(BandKeysTest, OneAndSixtyFourBands) {
  BandKeyArray keys{};
  ASSERT_TRUE(BandKeys(~uint64_t{0}, 1, &keys).ok());
  EXPECT_EQ(keys[0], ~uint64_t{0});
  ASSERT_TRUE(BandKeys(0x8000000000000001ULL, 64, &keys).ok());
  EXPECT_EQ(keys[0], 1U);
  EXPECT_EQ(keys[1], 0U);
  EXPECT_EQ(keys[63], 1U);
}

TEST(BandKeysTest, RejectsBadCounts) {
  BandKeyArray keys{};
  EXPECT_TRUE(absl::IsInvalidArgument(BandKeys(1, 0, &keys)));
  EXPECT_TRUE(absl::IsInvalidArgument(BandKeys(1, 65, &keys)));
  EXPECT_TRUE(absl::IsInvalidArgument(BandKeys(1, -1, &keys)));
}

}  // namespace
}  // namespace premarket::fastpath
