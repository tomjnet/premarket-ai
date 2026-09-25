// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Exact-duplicate flagging by content hash. Every item is kept; duplicates
// are only flagged (is_dup = true, dup_of = first copy).

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_INGEST_DEDUP_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_INGEST_DEDUP_H_

#include <map>
#include <string>
#include <vector>

#include "ingest/news_item.h"

namespace premarket {
namespace legacy {

// `known` maps content_hash -> vendor_item_id for items from earlier feeds
// (the dedup window). Walks `items` in feed order: an item is a duplicate
// when its hash is in `known` or appeared earlier in the same feed.
// Items must already have content_hash set. Returns the number flagged.
int FlagDuplicates(const std::map<std::string, std::string>& known,
                   std::vector<NewsItem>* items);

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_INGEST_DEDUP_H_
