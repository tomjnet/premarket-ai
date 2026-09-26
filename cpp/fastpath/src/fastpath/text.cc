// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "fastpath/text.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "absl/strings/ascii.h"

namespace premarket::fastpath {
namespace {

struct Entity {
  std::string_view name;
  char replacement;
};

// Checked in this order, like the reference.
constexpr std::array<Entity, 7> kEntities = {{
    {"&amp;", '&'},
    {"&lt;", '<'},
    {"&gt;", '>'},
    {"&quot;", '"'},
    {"&#39;", '\''},
    {"&apos;", '\''},
    {"&nbsp;", ' '},
}};

// Month names and the number words zero to twelve.
constexpr std::array<std::string_view, 25> kFactWords = {
    // clang-format off
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve",
    // clang-format on
};
constexpr size_t kMinFactWord = 3;
constexpr size_t kMaxFactWord = 9;

// " \t\n\r\f\v", the reference's _ASCII_SPACE.
bool IsAsciiSpace(char c) {
  return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' ||
         c == '\v';
}

bool IsDigit(char c) { return c >= '0' && c <= '9'; }

// "<" starts a tag only when one of these follows it ("x < 5" stays).
bool IsTagStart(char c) {
  return absl::ascii_isalpha(static_cast<unsigned char>(c)) || c == '/' ||
         c == '!' || c == '?';
}

bool IsAsciiAlnum(char c) {
  return absl::ascii_isalnum(static_cast<unsigned char>(c));
}

uint8_t Byte(std::string_view text, size_t i) {
  return static_cast<uint8_t>(text[i]);
}

// UTF-8 length of the invisible character starting at text[i], or 0:
// U+00AD (C2 AD), U+200B..U+200D (E2 80 8B..8D), U+2060 (E2 81 A0) and
// U+FEFF (EF BB BF). Lead bytes never appear as continuation bytes, so a
// match at any byte position is a match at a character boundary.
size_t InvisibleLength(std::string_view text, size_t i) {
  const size_t left = text.size() - i;
  const uint8_t b0 = Byte(text, i);
  if (b0 == 0xC2) {
    return left >= 2 && Byte(text, i + 1) == 0xAD ? 2 : 0;
  }
  if ((b0 != 0xE2 && b0 != 0xEF) || left < 3) return 0;
  const uint8_t b1 = Byte(text, i + 1);
  const uint8_t b2 = Byte(text, i + 2);
  if (b0 == 0xEF) return b1 == 0xBB && b2 == 0xBF ? 3 : 0;
  if (b1 == 0x80 && b2 >= 0x8B && b2 <= 0x8D) return 3;
  if (b1 == 0x81 && b2 == 0xA0) return 3;
  return 0;
}

// Appends characters to the output, collapsing whitespace like the
// reference's emit(): a space is only written when a character follows it
// and something was written before it.
class Emitter {
 public:
  explicit Emitter(std::string* out) : out_(out) {}

  void Space() { pending_space_ = !out_->empty(); }

  void Put(char c) {
    if (pending_space_) {
      out_->push_back(' ');
      pending_space_ = false;
    }
    out_->push_back(
        static_cast<char>(absl::ascii_tolower(static_cast<unsigned char>(c))));
  }

 private:
  std::string* out_;
  bool pending_space_ = false;
};

bool IsFactWord(std::string_view word) {
  if (word.size() < kMinFactWord || word.size() > kMaxFactWord) return false;
  return std::find(kFactWords.begin(), kFactWords.end(), word) !=
         kFactWords.end();
}

// Length of the match of \$?[0-9][0-9,]*(?:\.[0-9]+)?%? at text[i], or 0.
// Every part after [0-9,]* is optional, so the greedy first try is the
// match and no backtracking is needed.
size_t NumberLength(std::string_view text, size_t i) {
  const size_t size = text.size();
  size_t j = i;
  if (text[j] == '$') ++j;
  if (j >= size || !IsDigit(text[j])) return 0;
  ++j;
  while (j < size && (IsDigit(text[j]) || text[j] == ',')) ++j;
  if (j + 1 < size && text[j] == '.' && IsDigit(text[j + 1])) {
    j += 2;
    while (j < size && IsDigit(text[j])) ++j;
  }
  if (j < size && text[j] == '%') ++j;
  return j - i;
}

std::string_view StripNonAlnum(std::string_view token) {
  size_t start = 0;
  size_t end = token.size();
  while (start < end && !IsAsciiAlnum(token[start])) ++start;
  while (end > start && !IsAsciiAlnum(token[end - 1])) --end;
  return token.substr(start, end - start);
}

}  // namespace

void NormalizeText(std::string_view text, std::string* out) {
  out->clear();
  out->reserve(text.size());
  Emitter emit(out);
  const size_t size = text.size();
  // The first '>' at or after some earlier position: still the first one
  // after i + 1 while it's >= i + 1. Keeps "<a<a<a..." linear.
  size_t next_gt = 0;
  bool next_gt_known = false;
  size_t i = 0;
  while (i < size) {
    const char c = text[i];
    if (c == '<' && i + 1 < size && IsTagStart(text[i + 1])) {
      if (!next_gt_known ||
          (next_gt != std::string_view::npos && next_gt < i + 1)) {
        next_gt = text.find('>', i + 1);
        next_gt_known = true;
      }
      if (next_gt != std::string_view::npos) {
        emit.Space();
        i = next_gt + 1;
        continue;
      }
    }
    if (c == '&') {
      const std::string_view rest = text.substr(i);
      const auto* entity = std::find_if(
          kEntities.begin(), kEntities.end(),
          [rest](const Entity& e) { return rest.starts_with(e.name); });
      if (entity == kEntities.end()) {
        emit.Put(c);
        ++i;
      } else {
        if (IsAsciiSpace(entity->replacement)) {
          emit.Space();
        } else {
          emit.Put(entity->replacement);
        }
        i += entity->name.size();
      }
      continue;
    }
    if (IsAsciiSpace(c)) {
      emit.Space();
      ++i;
      continue;
    }
    if (Byte(text, i) >= 0x80) {
      const size_t skip = InvisibleLength(text, i);
      if (skip != 0) {
        i += skip;
        continue;
      }
    }
    // A non-ASCII byte is copied as is; ascii_tolower leaves it unchanged.
    emit.Put(c);
    ++i;
  }
}

void ExtractKeyNumbers(std::string_view text, std::vector<std::string>* out) {
  out->clear();
  const size_t size = text.size();
  size_t i = 0;
  while (i < size) {
    const size_t length = NumberLength(text, i);
    if (length == 0) {
      ++i;
      continue;
    }
    std::string& fact = out->emplace_back();
    for (const char c : text.substr(i, length)) {
      if (c != ',') fact.push_back(c);
    }
    i += length;
  }
  size_t start = 0;
  while (start <= size) {
    size_t end = text.find(' ', start);
    if (end == std::string_view::npos) end = size;
    const std::string_view word =
        StripNonAlnum(text.substr(start, end - start));
    if (IsFactWord(word)) out->emplace_back(word);
    start = end + 1;
  }
  std::sort(out->begin(), out->end());
  out->erase(std::unique(out->begin(), out->end()), out->end());
}

}  // namespace premarket::fastpath
