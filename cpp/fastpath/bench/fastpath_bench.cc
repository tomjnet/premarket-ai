// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Micro-benchmarks of the fastpath hot functions on a ~60-word news story.
// Build: cmake --preset release -DFASTPATH_BUILD_BENCH=ON, then run
// build/release/fastpath_bench --benchmark_enable_random_interleaving=true
// --benchmark_repetitions=10 for p50-like stability.

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "benchmark/benchmark.h"
#include "fastpath/hash.h"
#include "fastpath/text.h"

namespace premarket::fastpath {
namespace {

constexpr std::string_view kStory =
    "NEW YORK <b>NVIDIA</b> reports third-quarter revenue of $35.1B, up 94% "
    "from a year ago, beating analyst estimates of $33.2B. Data center "
    "revenue rose to $30.8B &amp; gaming revenue was $3.3B. The company "
    "expects fourth-quarter revenue of about $37.5B, plus or minus 2%, and "
    "said two new products will ship in March. Shares rose 3.5% in "
    "premarket trading on Thursday, after one analyst raised the target "
    "to $175.";

void BM_NormalizeText(benchmark::State& state) {
  std::string out;
  for (auto _ : state) {
    NormalizeText(kStory, &out);
    benchmark::DoNotOptimize(out.data());
    benchmark::ClobberMemory();
  }
  state.SetBytesProcessed(state.iterations() *
                          static_cast<int64_t>(kStory.size()));
}
BENCHMARK(BM_NormalizeText);

void BM_SimHash64(benchmark::State& state) {
  std::string text;
  NormalizeText(kStory, &text);
  const int ngram = static_cast<int>(state.range(0));
  for (auto _ : state) {
    absl::StatusOr<uint64_t> value = SimHash64(text, ngram);
    benchmark::DoNotOptimize(value);
  }
  state.SetBytesProcessed(state.iterations() *
                          static_cast<int64_t>(text.size()));
}
BENCHMARK(BM_SimHash64)->Arg(1)->Arg(2)->Arg(3);

void BM_ExtractKeyNumbers(benchmark::State& state) {
  std::string text;
  NormalizeText(kStory, &text);
  std::vector<std::string> facts;
  for (auto _ : state) {
    ExtractKeyNumbers(text, &facts);
    benchmark::DoNotOptimize(facts.data());
    benchmark::ClobberMemory();
  }
}
BENCHMARK(BM_ExtractKeyNumbers);

void BM_Sha256(benchmark::State& state) {
  std::string text;
  NormalizeText(kStory, &text);
  Sha256Hex hex;
  for (auto _ : state) {
    absl::Status status = Sha256(text, &hex);
    benchmark::DoNotOptimize(status);
    benchmark::DoNotOptimize(hex.data());
  }
}
BENCHMARK(BM_Sha256);

}  // namespace
}  // namespace premarket::fastpath

BENCHMARK_MAIN();
