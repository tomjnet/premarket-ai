// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/normalize.h"

#include "gtest/gtest.h"

namespace premarket {
namespace legacy {
namespace {

TEST(NormalizeTextTest, LowercasesAndCollapsesWhitespace) {
  EXPECT_EQ(NormalizeText("  Apple   REPORTS\tQ3\n\nRevenue  "),
            "apple reports q3 revenue");
}

TEST(NormalizeTextTest, KeepsNumbersAndPunctuation) {
  EXPECT_EQ(NormalizeText("Profit up 5%"), "profit up 5%");
  EXPECT_NE(NormalizeText("Profit up 5%"), NormalizeText("Profit up 50%"));
}

TEST(NormalizeTextTest, EmptyAndBlank) {
  EXPECT_EQ(NormalizeText(""), "");
  EXPECT_EQ(NormalizeText(" \t\n "), "");
}

TEST(Sha256HexTest, KnownVectors) {
  EXPECT_EQ(Sha256Hex(""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  EXPECT_EQ(Sha256Hex("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
}

TEST(ContentHashTest, CaseAndWhitespaceDoNotMatter) {
  EXPECT_EQ(ContentHash("[SYNTHETIC] Apple beats", "Revenue  rose 5%."),
            ContentHash("[SYNTHETIC] APPLE BEATS", "Revenue rose 5%.\n"));
}

TEST(ContentHashTest, OneWordChangesTheHash) {
  EXPECT_NE(ContentHash("Apple beats", "Revenue rose 5%."),
            ContentHash("Apple beats", "Revenue increased 5%."));
}

TEST(ContentHashTest, HeadlineAndBodyAreSeparated) {
  EXPECT_NE(ContentHash("a b", "c"), ContentHash("a", "b c"));
}

}  // namespace
}  // namespace legacy
}  // namespace premarket
