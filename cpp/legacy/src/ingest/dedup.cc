// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/dedup.h"

#include <cstddef>
#include <map>
#include <string>
#include <vector>

namespace premarket {
namespace legacy {

int FlagDuplicates(const std::map<std::string, std::string>& known,
                   std::vector<NewsItem>* items) {
  std::map<std::string, std::string> seen(known);
  int dups = 0;
  for (std::size_t i = 0; i < items->size(); ++i) {
    NewsItem& item = (*items)[i];
    std::map<std::string, std::string>::const_iterator it =
        seen.find(item.content_hash);
    if (it != seen.end()) {
      item.is_dup = true;
      item.dup_of = it->second;
      ++dups;
    } else {
      item.is_dup = false;
      item.dup_of.clear();
      seen[item.content_hash] = item.vendor_item_id;
    }
  }
  return dups;
}

}  // namespace legacy
}  // namespace premarket
