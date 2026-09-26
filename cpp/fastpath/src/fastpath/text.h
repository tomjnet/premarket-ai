// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Text normalization and fact extraction for the ai-api duplicate and rule
// checks. The spec is the pure-Python reference in
// python/ai-api/src/ai_api/dedup/normalize.py (ref_normalize_text and
// ref_extract_key_numbers); the parity tests compare the two on random
// input.
//
// Input is UTF-8. The reference only changes ASCII characters or drops the
// listed invisible characters, so working on bytes gives exactly the same
// result as working on code points.

#ifndef PREMARKET_AI_CPP_FASTPATH_SRC_FASTPATH_TEXT_H_
#define PREMARKET_AI_CPP_FASTPATH_SRC_FASTPATH_TEXT_H_

#include <string>
#include <string_view>
#include <vector>

namespace premarket::fastpath {

// Normalizes `text` into `*out` in one left-to-right pass: an HTML tag
// ("<" followed by a letter, "/", "!" or "?", up to the next ">"; without a
// ">" it's plain text) becomes a space; "&amp; &lt; &gt; &quot; &#39;
// &apos; &nbsp;" are decoded once (never parsed again); U+00AD, U+200B,
// U+200C, U+200D, U+2060 and U+FEFF are dropped; ASCII letters are
// lowercased; runs of ASCII whitespace become one space, trimmed.
//
// `*out` is cleared first and its capacity is reused, so a caller that keeps
// one buffer normalizes without allocating. The output is never longer than
// the input.
void NormalizeText(std::string_view text, std::string* out);

// Extracts the facts of a normalized story into `*out` (cleared first),
// sorted bytewise and unique: every match of
// \$?[0-9][0-9,]*(?:\.[0-9]+)?%? with the commas removed, plus the month
// names and the number words "zero" to "twelve" among the space-separated
// tokens (leading and trailing non-ASCII-alphanumeric bytes stripped).
//
// Facts are short, so they fit std::string's inline buffer: reusing `*out`
// normally allocates nothing.
void ExtractKeyNumbers(std::string_view text, std::vector<std::string>* out);

}  // namespace premarket::fastpath

#endif  // PREMARKET_AI_CPP_FASTPATH_SRC_FASTPATH_TEXT_H_
