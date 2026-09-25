// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "report/text_layout.h"

#include <cstddef>
#include <string>
#include <vector>

namespace premarket {
namespace legacy {
namespace {

std::vector<std::string> SplitWords(const std::string& text) {
  std::vector<std::string> words;
  std::string current;
  for (std::size_t i = 0; i < text.size(); ++i) {
    const char c = text[i];
    if (c == ' ' || c == '\t' || c == '\r') {
      if (!current.empty()) words.push_back(current);
      current.clear();
    } else {
      current.push_back(c);
    }
  }
  if (!current.empty()) words.push_back(current);
  return words;
}

}  // namespace

std::vector<std::string> WrapText(const std::string& paragraph, float max_width,
                                  const WidthFunction& width) {
  std::vector<std::string> lines;
  std::string line;
  const std::vector<std::string> words = SplitWords(paragraph);
  for (std::size_t w = 0; w < words.size(); ++w) {
    std::string word = words[w];
    std::string candidate = line;
    if (!candidate.empty()) candidate += ' ';
    candidate += word;
    if (width(candidate) <= max_width) {
      line = candidate;
      continue;
    }
    if (!line.empty()) {
      lines.push_back(line);
      line.clear();
    }
    // The word alone is too wide: cut it into pieces that fit.
    while (width(word) > max_width && word.size() > 1) {
      std::size_t cut = 1;
      while (cut < word.size() && width(word.substr(0, cut + 1)) <= max_width) {
        ++cut;
      }
      lines.push_back(word.substr(0, cut));
      word = word.substr(cut);
    }
    line = word;
  }
  if (!line.empty() || lines.empty()) lines.push_back(line);
  return lines;
}

std::vector<std::string> SplitParagraphs(const std::string& text) {
  std::vector<std::string> paragraphs;
  std::string current;
  for (std::size_t i = 0; i < text.size(); ++i) {
    if (text[i] == '\n') {
      paragraphs.push_back(current);
      current.clear();
    } else {
      current.push_back(text[i]);
    }
  }
  paragraphs.push_back(current);
  return paragraphs;
}

std::string ToPrintableAscii(const std::string& text) {
  std::string out;
  out.reserve(text.size());
  for (std::size_t i = 0; i < text.size(); ++i) {
    const unsigned char c = static_cast<unsigned char>(text[i]);
    if (c == '\n' || (c >= 0x20 && c < 0x7f)) {
      out.push_back(static_cast<char>(c));
    } else if ((c & 0xc0) != 0x80) {
      // One '?' per UTF-8 character: skip continuation bytes.
      out.push_back('?');
    }
  }
  return out;
}

}  // namespace legacy
}  // namespace premarket
