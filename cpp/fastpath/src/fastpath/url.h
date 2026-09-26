// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// URL canonicalization: the L0 (exact URL) duplicate key. The spec is
// ref_canonical_url in python/ai-api/src/ai_api/dedup/normalize.py.

#ifndef PREMARKET_AI_CPP_FASTPATH_SRC_FASTPATH_URL_H_
#define PREMARKET_AI_CPP_FASTPATH_SRC_FASTPATH_URL_H_

#include <string>
#include <string_view>

#include "absl/status/status.h"

namespace premarket::fastpath {

// Writes the canonical form of `url` to `*out` (cleared first; capacity is
// reused). Strips ASCII whitespace; lowercases the scheme and host; drops a
// default port (http:80, https:443) or an empty one, the fragment, trailing
// slashes of the path and tracking parameters (utm_*, ref, ref_src, fbclid,
// gclid, igshid, mc_cid, mc_eid; keys compared in ASCII lowercase); sorts
// the remaining query parameters bytewise. User info, path and parameter
// values keep their case. An IPv6 host keeps its brackets.
//
// Returns InvalidArgument when `url` has no valid "scheme://" or no host;
// `*out` is then unspecified.
absl::Status CanonicalUrl(std::string_view url, std::string* out);

}  // namespace premarket::fastpath

#endif  // PREMARKET_AI_CPP_FASTPATH_SRC_FASTPATH_URL_H_
