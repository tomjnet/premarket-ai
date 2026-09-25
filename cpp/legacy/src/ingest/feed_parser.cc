// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/feed_parser.h"

#include <cstddef>
#include <string>
#include <vector>

#include "rapidjson/document.h"
#include "rapidjson/error/en.h"
#include "rapidjson/stringbuffer.h"
#include "rapidjson/writer.h"

namespace premarket {
namespace legacy {
namespace {

std::string ParseErrorText(const rapidjson::Document& doc) {
  return std::string(rapidjson::GetParseError_En(doc.GetParseError())) +
         " at offset " + std::to_string(doc.GetErrorOffset());
}

// Copies the string member `key` of `object` into `out`.
Status GetString(const rapidjson::Value& object, const char* key,
                 std::string* out) {
  rapidjson::Value::ConstMemberIterator it = object.FindMember(key);
  if (it == object.MemberEnd()) {
    return InvalidArgumentError(std::string("missing field '") + key + "'");
  }
  if (!it->value.IsString()) {
    return InvalidArgumentError(std::string("field '") + key +
                                "' is not a string");
  }
  out->assign(it->value.GetString(), it->value.GetStringLength());
  return OkStatus();
}

Status ItemError(const std::string& id, const char* what) {
  return InvalidArgumentError("item " + id + ": " + what);
}

}  // namespace

StatusOr<std::vector<std::string>> SplitFeed(const std::string& feed_json) {
  rapidjson::Document doc;
  doc.Parse(feed_json.c_str(), feed_json.size());
  if (doc.HasParseError()) {
    return InvalidArgumentError("feed is not valid JSON: " +
                                ParseErrorText(doc));
  }
  if (!doc.IsObject()) {
    return InvalidArgumentError("feed must be a JSON object");
  }
  rapidjson::Value::ConstMemberIterator items = doc.FindMember("items");
  if (items == doc.MemberEnd() || !items->value.IsArray()) {
    return InvalidArgumentError("feed has no 'items' array");
  }

  std::vector<std::string> out;
  out.reserve(items->value.Size());
  for (rapidjson::SizeType i = 0; i < items->value.Size(); ++i) {
    rapidjson::StringBuffer buffer;
    rapidjson::Writer<rapidjson::StringBuffer> writer(buffer);
    items->value[i].Accept(writer);
    out.push_back(std::string(buffer.GetString(), buffer.GetSize()));
  }
  return out;
}

StatusOr<NewsItem> ParseItem(const std::string& item_json) {
  rapidjson::Document doc;
  doc.Parse(item_json.c_str(), item_json.size());
  if (doc.HasParseError()) {
    return InvalidArgumentError("item is not valid JSON: " +
                                ParseErrorText(doc));
  }
  if (!doc.IsObject()) {
    return InvalidArgumentError("item must be a JSON object");
  }

  NewsItem item;
  Status status = GetString(doc, "id", &item.vendor_item_id);
  if (status.ok()) status = GetString(doc, "headline", &item.headline);
  if (status.ok()) status = GetString(doc, "body", &item.body);
  if (status.ok()) status = GetString(doc, "source_url", &item.source_url);
  if (status.ok()) {
    status = GetString(doc, "source_domain", &item.source_domain);
  }
  if (status.ok()) status = GetString(doc, "published_at", &item.published_at);
  if (!status.ok()) return status;
  if (item.vendor_item_id.empty()) {
    return InvalidArgumentError("field 'id' is empty");
  }

  rapidjson::Value::ConstMemberIterator tickers = doc.FindMember("tickers");
  if (tickers == doc.MemberEnd() || !tickers->value.IsArray()) {
    return ItemError(item.vendor_item_id, "'tickers' must be an array");
  }
  for (rapidjson::SizeType i = 0; i < tickers->value.Size(); ++i) {
    const rapidjson::Value& ticker = tickers->value[i];
    if (!ticker.IsString()) {
      return ItemError(item.vendor_item_id, "ticker is not a string");
    }
    item.tickers.push_back(
        std::string(ticker.GetString(), ticker.GetStringLength()));
  }

  rapidjson::Value::ConstMemberIterator synthetic = doc.FindMember("synthetic");
  if (synthetic != doc.MemberEnd()) {
    if (!synthetic->value.IsBool()) {
      return ItemError(item.vendor_item_id, "'synthetic' must be a boolean");
    }
    item.synthetic = synthetic->value.GetBool();
  }
  return item;
}

}  // namespace legacy
}  // namespace premarket
