// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Expected values come from the Python reference (ref_normalize_text and
// ref_extract_key_numbers in python/ai-api/src/ai_api/dedup/normalize.py).

#include "fastpath/text.h"

#include <string>
#include <string_view>
#include <vector>

#include "gtest/gtest.h"

namespace premarket::fastpath {
namespace {

std::string Normalize(std::string_view text) {
  std::string out;
  NormalizeText(text, &out);
  return out;
}

std::vector<std::string> KeyNumbers(std::string_view text) {
  std::vector<std::string> out;
  ExtractKeyNumbers(text, &out);
  return out;
}

using Facts = std::vector<std::string>;

TEST(NormalizeTextTest, DocstringExample) {
  EXPECT_EQ(Normalize("NVIDIA <b>reports</b> Q3 revenue of $35.1B, up 94%"),
            "nvidia reports q3 revenue of $35.1b, up 94%");
}

TEST(NormalizeTextTest, Empty) { EXPECT_EQ(Normalize(""), ""); }

TEST(NormalizeTextTest, TagBecomesSpace) {
  EXPECT_EQ(Normalize("a<b>c"), "a c");
  EXPECT_EQ(Normalize("a</p>c"), "a c");
  EXPECT_EQ(Normalize("a<!-- x -->c"), "a c");
  EXPECT_EQ(Normalize("a<?xml?>c"), "a c");
  EXPECT_EQ(Normalize("<p>x</p>"), "x");
}

TEST(NormalizeTextTest, LessThanWithoutTagStartIsText) {
  EXPECT_EQ(Normalize("x < 5 and <a"), "x < 5 and <a");
  EXPECT_EQ(Normalize("<>x"), "<>x");
  EXPECT_EQ(Normalize("<1>"), "<1>");
  EXPECT_EQ(Normalize("<"), "<");
}

TEST(NormalizeTextTest, TagRunsToTheFirstClosingBracket) {
  EXPECT_EQ(Normalize("<a <b> c"), "c");
  EXPECT_EQ(Normalize("<a>>"), ">");
}

TEST(NormalizeTextTest, TagWithoutClosingBracketIsText) {
  EXPECT_EQ(Normalize("<a<a<a"), "<a<a<a");
  EXPECT_EQ(Normalize("<a>x<b"), "x<b");
}

TEST(NormalizeTextTest, EntitiesAreDecodedOnce) {
  EXPECT_EQ(Normalize("a&amp;lt;b"), "a&lt;b");
  EXPECT_EQ(Normalize("&lt;b&gt;"), "<b>");
  EXPECT_EQ(Normalize("&quot;&#39;&apos;"), "\"''");
  EXPECT_EQ(Normalize("&AMP; &#39;&apos;&quot;&gt;"), "&amp; ''\">");
}

TEST(NormalizeTextTest, UnknownEntityIsText) {
  EXPECT_EQ(Normalize("&"), "&");
  EXPECT_EQ(Normalize("a &x b"), "a &x b");
  EXPECT_EQ(Normalize("&amp"), "&amp");
}

TEST(NormalizeTextTest, NbspIsWhitespace) {
  EXPECT_EQ(Normalize("&nbsp;&nbsp;x&nbsp;"), "x");
  EXPECT_EQ(Normalize("a&nbsp; b"), "a b");
}

TEST(NormalizeTextTest, WhitespaceCollapsedAndTrimmed) {
  EXPECT_EQ(Normalize("  Hello\t\n World  "), "hello world");
  EXPECT_EQ(Normalize("a\r\f\vb"), "a b");
  EXPECT_EQ(Normalize(" \t "), "");
}

TEST(NormalizeTextTest, OtherWhitespaceIsKept) {
  // Only " \t\n\r\f\v" is whitespace: U+001C and U+00A0 are text.
  // Non-ASCII characters are written as octal UTF-8 bytes.
  EXPECT_EQ(Normalize("a\034b"), "a\034b");
  EXPECT_EQ(Normalize("a\302\240b"), "a\302\240b");
}

TEST(NormalizeTextTest, OnlyAsciiIsLowercased) {
  // U+00C9, U+00DF, U+0130.
  EXPECT_EQ(Normalize("Caf\303\211 \303\237 \304\260"),
            "caf\303\211 \303\237 \304\260");
}

TEST(NormalizeTextTest, InvisibleCharactersAreDropped) {
  // U+00AD, U+200B, U+200C, U+200D, U+2060, U+FEFF.
  EXPECT_EQ(Normalize("a\302\255b\342\200\213c\342\200\214d\342\200\215e"
                      "\342\201\240f\357\273\277g"),
            "abcdefg");
  EXPECT_EQ(Normalize(" \342\200\213 x"), "x");
  EXPECT_EQ(Normalize("x \342\200\213 y"), "x y");
  EXPECT_EQ(Normalize("x\342\200\213"), "x");
}

TEST(NormalizeTextTest, NeighboursOfInvisibleCharactersAreKept) {
  // U+00AE, U+200A, U+200E, U+2061, U+FEFE: same lead bytes, visible.
  const std::string kept =
      "\302\256\342\200\212\342\200\216\342\201\241\357\273\276";
  EXPECT_EQ(Normalize(kept), kept);
  // Truncated sequences at the end are just bytes.
  EXPECT_EQ(Normalize("\xe2\x80"), "\xe2\x80");
  EXPECT_EQ(Normalize("\xc2"), "\xc2");
}

TEST(NormalizeTextTest, ReusesTheBuffer) {
  std::string out = "stale";
  NormalizeText("A", &out);
  EXPECT_EQ(out, "a");
}

TEST(ExtractKeyNumbersTest, Story) {
  EXPECT_EQ(KeyNumbers("profit up 5% to $85.1b in march, one of two"),
            (Facts{"$85.1", "5%", "march", "one", "two"}));
}

TEST(ExtractKeyNumbersTest, Empty) { EXPECT_EQ(KeyNumbers(""), Facts{}); }

TEST(ExtractKeyNumbersTest, NumberRegexEdgeCases) {
  EXPECT_EQ(KeyNumbers("1,234,5.6.7 $ $5 5.% 3. .5 12,,3%"),
            (Facts{"$5", "123%", "12345.6", "3", "5", "7"}));
  EXPECT_EQ(KeyNumbers("x1.2y"), Facts{"1.2"});
  EXPECT_EQ(KeyNumbers("$1,000.50% "), Facts{"$1000.50%"});
  EXPECT_EQ(KeyNumbers("$$5"), Facts{"$5"});
  EXPECT_EQ(KeyNumbers(","), Facts{});
}

TEST(ExtractKeyNumbersTest, FactWordsAreStrippedTokens) {
  EXPECT_EQ(KeyNumbers("(two) june, may-june twelve twelve"),
            (Facts{"june", "twelve", "two"}));
  EXPECT_EQ(KeyNumbers("hello \346\227\245one\346\227\245"), Facts{"one"});
  // Tokens are split on single spaces only.
  EXPECT_EQ(KeyNumbers("one\ttwo"), Facts{});
  EXPECT_EQ(KeyNumbers("One"), Facts{});
}

TEST(ExtractKeyNumbersTest, SortedAndUnique) {
  EXPECT_EQ(KeyNumbers("9 10 9 ten 1,0"), (Facts{"10", "9", "ten"}));
}

}  // namespace
}  // namespace premarket::fastpath
