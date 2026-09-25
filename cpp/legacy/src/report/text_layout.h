// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Word wrapping and character cleanup for the PDF report.

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_REPORT_TEXT_LAYOUT_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_REPORT_TEXT_LAYOUT_H_

#include <functional>
#include <string>
#include <vector>

namespace premarket {
namespace legacy {

// Returns the rendered width of a string (for example in PDF points).
typedef std::function<float(const std::string&)> WidthFunction;

// Greedy word wrap of one paragraph so that every line fits `max_width`.
// A single word wider than a line is split by characters. Whitespace runs
// become single spaces. An empty paragraph gives one empty line.
std::vector<std::string> WrapText(const std::string& paragraph, float max_width,
                                  const WidthFunction& width);

// Splits `text` on '\n' into paragraphs (empty ones kept).
std::vector<std::string> SplitParagraphs(const std::string& text);

// The built-in PDF fonts use WinAnsi encoding: keep printable ASCII and
// replace every other byte (including UTF-8 sequences) with '?'.
std::string ToPrintableAscii(const std::string& text);

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_REPORT_TEXT_LAYOUT_H_
