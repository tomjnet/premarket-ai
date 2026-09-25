// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "report/text_layout.h"

#include <cstddef>
#include <string>
#include <vector>

#include "gtest/gtest.h"

namespace premarket {
namespace legacy {
namespace {

// One unit per character, so max_width is a character count.
float CharWidth(const std::string& text) {
  return static_cast<float>(text.size());
}

TEST(WrapTextTest, GreedyWrap) {
  const std::vector<std::string> lines =
      WrapText("the quick brown fox jumps over", 10.0f, &CharWidth);
  ASSERT_EQ(lines.size(), 3u);
  EXPECT_EQ(lines[0], "the quick");
  EXPECT_EQ(lines[1], "brown fox");
  EXPECT_EQ(lines[2], "jumps over");
}

TEST(WrapTextTest, EveryLineFits) {
  const std::vector<std::string> lines = WrapText(
      "Sales at a large company rose 12% to $41.2 billion in fiscal Q3.", 16.0f,
      &CharWidth);
  for (size_t i = 0; i < lines.size(); ++i) {
    EXPECT_LE(lines[i].size(), 16u) << lines[i];
  }
}

TEST(WrapTextTest, SplitsVeryLongWords) {
  const std::vector<std::string> lines =
      WrapText("https://example.test/very/long/path", 10.0f, &CharWidth);
  ASSERT_GE(lines.size(), 4u);
  std::string joined;
  for (size_t i = 0; i < lines.size(); ++i) {
    EXPECT_LE(lines[i].size(), 10u);
    joined += lines[i];
  }
  EXPECT_EQ(joined, "https://example.test/very/long/path");
}

TEST(WrapTextTest, EmptyParagraphIsOneEmptyLine) {
  const std::vector<std::string> lines = WrapText("", 10.0f, &CharWidth);
  ASSERT_EQ(lines.size(), 1u);
  EXPECT_EQ(lines[0], "");
}

TEST(SplitParagraphsTest, KeepsEmptyParagraphs) {
  const std::vector<std::string> parts = SplitParagraphs("a\n\nb");
  ASSERT_EQ(parts.size(), 3u);
  EXPECT_EQ(parts[0], "a");
  EXPECT_EQ(parts[1], "");
  EXPECT_EQ(parts[2], "b");
}

TEST(ToPrintableAsciiTest, ReplacesNonAscii) {
  EXPECT_EQ(ToPrintableAscii("Caf\xc3\xa9 \xe2\x80\x94 ok\n"), "Caf? ? ok\n");
  EXPECT_EQ(ToPrintableAscii("tab\there"), "tab?here");
}

}  // namespace
}  // namespace legacy
}  // namespace premarket
