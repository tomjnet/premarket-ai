// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// The Python module premarket_fastpath (nanobind). The functions match the
// pure-Python reference in python/ai-api/src/ai_api/dedup (normalize.py and
// simhash.py) exactly; test_fastpath_parity.py checks it.
//
// This file is the one exception to the no-exceptions rule: nanobind
// reports errors to Python by throwing, so only this target is compiled
// with exceptions. The core (fastpath_core) never throws; every non-OK
// absl::Status it returns is turned into a Python ValueError here.

#include <nanobind/nanobind.h>
#include <nanobind/stl/string_view.h>

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "fastpath/hash.h"
#include "fastpath/text.h"
#include "fastpath/url.h"

namespace premarket::fastpath {
namespace {

namespace nb = nanobind;

void ThrowIfError(const absl::Status& status) {
  if (!status.ok()) {
    throw nb::value_error(std::string(status.message()).c_str());
  }
}

// Per-thread scratch buffers: their capacity is reused across calls.
std::string& TextBuffer() {
  thread_local std::string buffer;
  return buffer;
}

nb::str NormalizeTextPy(std::string_view text) {
  std::string& out = TextBuffer();
  NormalizeText(text, &out);
  return nb::str(out.data(), out.size());
}

nb::str CanonicalUrlPy(std::string_view url) {
  std::string& out = TextBuffer();
  ThrowIfError(CanonicalUrl(url, &out));
  return nb::str(out.data(), out.size());
}

nb::str Sha256Py(std::string_view text) {
  Sha256Hex hex;
  ThrowIfError(Sha256(text, &hex));
  return nb::str(hex.data(), hex.size());
}

nb::list ExtractKeyNumbersPy(std::string_view text) {
  thread_local std::vector<std::string> facts;
  ExtractKeyNumbers(text, &facts);
  nb::list result;
  for (const std::string& fact : facts) {
    result.append(nb::str(fact.data(), fact.size()));
  }
  return result;
}

uint64_t SimHash64Py(std::string_view text, int ngram) {
  const absl::StatusOr<uint64_t> value = SimHash64(text, ngram);
  ThrowIfError(value.status());
  return *value;
}

nb::list BandKeysPy(uint64_t value, int bands) {
  BandKeyArray keys;
  ThrowIfError(BandKeys(value, bands, &keys));
  nb::list result;
  for (int i = 0; i < bands; ++i) result.append(keys[i]);
  return result;
}

}  // namespace
}  // namespace premarket::fastpath

NB_MODULE(premarket_fastpath, m) {
  namespace fp = premarket::fastpath;
  namespace nb = nanobind;
  m.doc() =
      "C++20 fast path of the ai-api duplicate and rule checks. Every "
      "function returns exactly what its ref_* Python reference returns.";
  m.def("normalize_text", &fp::NormalizeTextPy, nb::arg("text"),
        "Tags to a space, a few entities decoded, invisible characters "
        "dropped, ASCII lowercased, ASCII whitespace collapsed and trimmed.");
  m.def("canonical_url", &fp::CanonicalUrlPy, nb::arg("url"),
        "The canonical URL (L0 duplicate key). Raises ValueError when the "
        "URL has no valid scheme:// or no host.");
  m.def("sha256", &fp::Sha256Py, nb::arg("text"),
        "Lowercase hex SHA-256 of the UTF-8 text.");
  m.def("extract_key_numbers", &fp::ExtractKeyNumbersPy, nb::arg("text"),
        "Sorted, unique numbers, month names and number words.");
  m.def("simhash64", &fp::SimHash64Py, nb::arg("text"), nb::arg("ngram") = 2,
        "64-bit SimHash of word n-grams. Raises ValueError unless "
        "1 <= ngram <= 8.");
  m.def("hamming", &fp::Hamming, nb::arg("a"), nb::arg("b"),
        "The number of bits in which two 64-bit hashes differ.");
  m.def("band_keys", &fp::BandKeysPy, nb::arg("value"), nb::arg("bands"),
        "The value of each of `bands` bit slices, lowest bits first. Raises "
        "ValueError unless 1 <= bands <= 64.");
}
