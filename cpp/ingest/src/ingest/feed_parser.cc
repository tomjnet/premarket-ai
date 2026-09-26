// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/feed_parser.h"

#include <simdjson.h>

#include <array>
#include <cstddef>
#include <cstring>
#include <memory>
#include <string_view>

#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "absl/strings/str_cat.h"

namespace premarket::ingest {
namespace {

using simdjson::SUCCESS;
namespace dom = simdjson::dom;

// Views the string member `key` of `object`.
ItemError GetString(const dom::object& object, std::string_view key,
                    std::string_view* out) {
  dom::element value;
  if (object.at_key(key).get(value) != SUCCESS) {
    return ItemError::kMissingField;
  }
  if (value.get_string().get(*out) != SUCCESS) return ItemError::kNotString;
  return ItemError::kNone;
}

bool Fail(NewsItem* item, ItemError error, const char* field) {
  item->error = error;
  item->error_field = field;
  return false;
}

}  // namespace

FeedBuffer::FeedBuffer(std::size_t capacity)
    : capacity_(capacity),
      // NOLINTNEXTLINE(modernize-avoid-c-arrays): no zero fill of the buffer
      data_(std::make_unique_for_overwrite<char[]>(
          capacity + simdjson::SIMDJSON_PADDING)) {
  Clear();
}

void FeedBuffer::Clear() {
  size_ = 0;
  ZeroPadding();
}

// simdjson reads (never uses) the padding after the last byte; keep it
// initialized without touching the rest of the (large) buffer.
void FeedBuffer::ZeroPadding() {
  std::memset(data_.get() + size_, 0, simdjson::SIMDJSON_PADDING);
}

bool FeedBuffer::Append(const char* bytes, std::size_t count) {
  if (count > capacity_ - size_) return false;
  std::memcpy(data_.get() + size_, bytes, count);
  size_ += count;
  ZeroPadding();
  return true;
}

absl::StatusOr<std::unique_ptr<FeedParser>> FeedParser::Create(
    std::size_t max_feed_bytes, std::size_t max_items) {
  std::unique_ptr<FeedParser> parser(new FeedParser(max_items));
  const simdjson::error_code error = parser->parser_.allocate(max_feed_bytes);
  if (error != SUCCESS) {
    return absl::ResourceExhaustedError(
        absl::StrCat("cannot allocate the JSON parser for ", max_feed_bytes,
                     " bytes: ", simdjson::error_message(error)));
  }
  parser->items_.reserve(max_items);
  return parser;
}

absl::Status FeedParser::Parse(const FeedBuffer& feed) {
  items_.clear();
  dom::element root;
  // realloc_if_needed = false: the buffer already carries the padding.
  simdjson::error_code error =
      parser_.parse(feed.data(), feed.size(), false).get(root);
  if (error != SUCCESS) {
    return absl::InvalidArgumentError(absl::StrCat(
        "feed is not valid JSON: ", simdjson::error_message(error)));
  }
  dom::object object;
  if (root.get_object().get(object) != SUCCESS) {
    return absl::InvalidArgumentError("feed must be a JSON object");
  }
  dom::array items;
  if (object.at_key("items").get_array().get(items) != SUCCESS) {
    return absl::InvalidArgumentError("feed has no 'items' array");
  }
  for (const dom::element item : items) {
    if (items_.size() == max_items_) {
      items_.clear();
      return absl::ResourceExhaustedError(absl::StrCat(
          "feed has more than INGEST_MAX_ITEMS=", max_items_, " items"));
    }
    items_.push_back(item);  // reserved: no allocation
  }
  return absl::OkStatus();
}

bool FeedParser::ExtractItem(std::size_t index, NewsItem* item) const {
  *item = NewsItem{};
  dom::object object;
  if (items_[index].get_object().get(object) != SUCCESS) {
    return Fail(item, ItemError::kNotObject, "");
  }

  struct Field {
    const char* name;
    std::string_view* out;
  };
  const std::array<Field, 6> fields = {{
      {"id", &item->vendor_item_id},
      {"headline", &item->headline},
      {"body", &item->body},
      {"source_url", &item->source_url},
      {"source_domain", &item->source_domain},
      {"published_at", &item->published_at},
  }};
  for (const Field& field : fields) {
    const ItemError error = GetString(object, field.name, field.out);
    if (error != ItemError::kNone) return Fail(item, error, field.name);
  }
  if (item->vendor_item_id.empty()) {
    return Fail(item, ItemError::kEmptyId, "id");
  }

  dom::array tickers;
  if (object.at_key("tickers").get_array().get(tickers) != SUCCESS) {
    return Fail(item, ItemError::kTickersNotArray, "tickers");
  }
  for (const dom::element ticker : tickers) {
    std::string_view text;
    if (ticker.get_string().get(text) != SUCCESS) {
      return Fail(item, ItemError::kTickerNotString, "tickers");
    }
    if (item->ticker_count == kMaxTickers) {
      return Fail(item, ItemError::kTooManyTickers, "tickers");
    }
    item->ticker_storage[item->ticker_count++] = text;
  }

  dom::element synthetic;
  if (object.at_key("synthetic").get(synthetic) == SUCCESS) {
    if (synthetic.get_bool().get(item->synthetic) != SUCCESS) {
      return Fail(item, ItemError::kSyntheticNotBool, "synthetic");
    }
  }
  return true;
}

absl::Status ItemErrorStatus(const NewsItem& item) {
  const std::string_view field = item.error_field;
  switch (item.error) {
    case ItemError::kNone:
      return absl::OkStatus();
    case ItemError::kNotObject:
      return absl::InvalidArgumentError("item must be a JSON object");
    case ItemError::kMissingField:
      return absl::InvalidArgumentError(
          absl::StrCat("missing field '", field, "'"));
    case ItemError::kNotString:
      return absl::InvalidArgumentError(
          absl::StrCat("field '", field, "' is not a string"));
    case ItemError::kEmptyId:
      return absl::InvalidArgumentError("field 'id' is empty");
    case ItemError::kTickersNotArray:
      return absl::InvalidArgumentError(absl::StrCat(
          "item ", item.vendor_item_id, ": 'tickers' must be an array"));
    case ItemError::kTickerNotString:
      return absl::InvalidArgumentError(absl::StrCat(
          "item ", item.vendor_item_id, ": ticker is not a string"));
    case ItemError::kTooManyTickers:
      return absl::InvalidArgumentError(
          absl::StrCat("item ", item.vendor_item_id, ": more than ",
                       kMaxTickers, " tickers"));
    case ItemError::kSyntheticNotBool:
      return absl::InvalidArgumentError(absl::StrCat(
          "item ", item.vendor_item_id, ": 'synthetic' must be a boolean"));
    case ItemError::kHashFailed:
      return absl::InternalError(
          absl::StrCat("item ", item.vendor_item_id, ": SHA-256 failed"));
  }
  return absl::InternalError("unknown item error");
}

}  // namespace premarket::ingest
