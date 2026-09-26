// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/dedup.h"

#include <span>

namespace premarket::ingest {

int FlagDuplicates(std::span<NewsItem> items, HashIndex* seen) {
  seen->reserve(seen->size() + items.size());  // no rehash inside the loop
  int dups = 0;
  for (NewsItem& item : items) {
    const auto [it, inserted] =
        seen->try_emplace(item.hash(), item.vendor_item_id);
    if (inserted) {
      item.is_dup = false;
      item.dup_of = {};
    } else {
      item.is_dup = true;
      item.dup_of = it->second;
      ++dups;
    }
  }
  return dups;
}

}  // namespace premarket::ingest
