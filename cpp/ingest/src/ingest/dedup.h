// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Exact-duplicate flagging by content hash. Every item is kept; duplicates
// are only flagged (is_dup = true, dup_of = first copy). Same rule as
// legacy's FlagDuplicates, with an open-addressing hash map of views
// (reserved up front) instead of a std::map of string copies.

#ifndef PREMARKET_AI_CPP_INGEST_SRC_INGEST_DEDUP_H_
#define PREMARKET_AI_CPP_INGEST_SRC_INGEST_DEDUP_H_

#include <span>
#include <string_view>

#include "absl/container/flat_hash_map.h"
#include "ingest/news_item.h"

namespace premarket::ingest {

// content_hash -> vendor_item_id of the first copy.
using HashIndex = absl::flat_hash_map<std::string_view, std::string_view>;

// On entry `seen` holds the hashes of earlier feeds (the dedup window).
// Walks `items` in feed order: an item is a duplicate when its hash is in
// `seen` or appeared earlier in the same feed; first copies are added to
// `seen`. Items must already have content_hash set, and the views must
// outlive `seen` and the items. Returns the number flagged.
int FlagDuplicates(std::span<NewsItem> items, HashIndex* seen);

}  // namespace premarket::ingest

#endif  // PREMARKET_AI_CPP_INGEST_SRC_INGEST_DEDUP_H_
