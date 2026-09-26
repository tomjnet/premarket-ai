// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "fastpath/url.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <optional>
#include <string>
#include <string_view>

#include "absl/container/inlined_vector.h"
#include "absl/status/status.h"
#include "absl/strings/ascii.h"
#include "absl/strings/match.h"
#include "absl/strings/str_cat.h"

namespace premarket::fastpath {
namespace {

constexpr std::array<std::string_view, 7> kTrackingKeys = {
    "ref", "ref_src", "fbclid", "gclid", "igshid", "mc_cid", "mc_eid",
};

struct HostPort {
  std::string_view host;
  std::optional<std::string_view> port;
};

// [A-Za-z][A-Za-z0-9+.\-]* over the whole scheme.
bool IsValidScheme(std::string_view scheme) {
  if (scheme.empty() ||
      !absl::ascii_isalpha(static_cast<unsigned char>(scheme.front()))) {
    return false;
  }
  return std::all_of(scheme.begin() + 1, scheme.end(), [](char c) {
    return absl::ascii_isalnum(static_cast<unsigned char>(c)) || c == '+' ||
           c == '.' || c == '-';
  });
}

// Splits "host[:port]"; an IPv6 host keeps its brackets. "[v6]x" (no ':'
// after "]") is all host; without "]" it's split on the last ':'.
HostPort SplitHostPort(std::string_view hostport) {
  if (hostport.starts_with('[')) {
    const size_t end = hostport.find(']');
    if (end != std::string_view::npos) {
      const std::string_view rest = hostport.substr(end + 1);
      if (rest.starts_with(':')) {
        return {hostport.substr(0, end + 1), rest.substr(1)};
      }
      return {hostport, std::nullopt};
    }
  }
  const size_t colon = hostport.rfind(':');
  if (colon == std::string_view::npos) return {hostport, std::nullopt};
  return {hostport.substr(0, colon), hostport.substr(colon + 1)};
}

bool IsDefaultPort(std::string_view scheme, std::string_view port) {
  return (scheme == "http" && port == "80") ||
         (scheme == "https" && port == "443");
}

// Keys are compared in ASCII lowercase; other bytes must match exactly.
bool IsTracking(std::string_view param) {
  const std::string_view key = param.substr(0, param.find('='));
  if (absl::StartsWithIgnoreCase(key, "utm_")) return true;
  return std::any_of(
      kTrackingKeys.begin(), kTrackingKeys.end(),
      [key](std::string_view k) { return absl::EqualsIgnoreCase(key, k); });
}

void AppendAsciiLower(std::string_view text, std::string* out) {
  for (const char c : text) {
    out->push_back(
        static_cast<char>(absl::ascii_tolower(static_cast<unsigned char>(c))));
  }
}

}  // namespace

absl::Status CanonicalUrl(std::string_view url, std::string* out) {
  out->clear();
  // absl's ASCII whitespace is exactly " \t\n\v\f\r".
  const std::string_view text = absl::StripAsciiWhitespace(url);
  const size_t separator = text.find("://");
  if (separator == std::string_view::npos ||
      !IsValidScheme(text.substr(0, separator))) {
    return absl::InvalidArgumentError(
        absl::StrCat("not an absolute URL: ", url));
  }
  const std::string_view scheme = text.substr(0, separator);
  std::string_view rest = text.substr(separator + 3);
  rest = rest.substr(0, rest.find('#'));
  const size_t cut = std::min(rest.find_first_of("/?"), rest.size());
  const std::string_view authority = rest.substr(0, cut);
  const std::string_view tail = rest.substr(cut);

  const size_t at = authority.rfind('@');
  const bool has_userinfo = at != std::string_view::npos;
  const std::string_view hostport =
      has_userinfo ? authority.substr(at + 1) : authority;
  auto [host, port] = SplitHostPort(hostport);
  if (host.empty()) {
    return absl::InvalidArgumentError(absl::StrCat("URL has no host: ", url));
  }

  out->reserve(text.size());
  AppendAsciiLower(scheme, out);
  // Compare the default ports against the lowercased scheme.
  const std::string_view lower_scheme(*out);
  if (port.has_value() &&
      (port->empty() || IsDefaultPort(lower_scheme, *port))) {
    port.reset();
  }
  out->append("://");
  if (has_userinfo) {
    out->append(authority.substr(0, at + 1));  // User info and the '@'.
  }
  AppendAsciiLower(host, out);
  if (port.has_value()) {
    out->push_back(':');
    out->append(*port);
  }

  const size_t question = tail.find('?');
  std::string_view path = tail.substr(0, question);
  while (path.ends_with('/')) path.remove_suffix(1);
  out->append(path);
  if (question == std::string_view::npos) return absl::OkStatus();

  absl::InlinedVector<std::string_view, 16> params;
  std::string_view query = tail.substr(question + 1);
  while (true) {
    const size_t amp = query.find('&');
    const std::string_view param = query.substr(0, amp);
    if (!param.empty() && !IsTracking(param)) params.push_back(param);
    if (amp == std::string_view::npos) break;
    query.remove_prefix(amp + 1);
  }
  // std::string_view compares bytewise as unsigned char: the same order as
  // Python's code point order for UTF-8.
  std::sort(params.begin(), params.end());
  char joiner = '?';
  for (const std::string_view param : params) {
    out->push_back(joiner);
    out->append(param);
    joiner = '&';
  }
  return absl::OkStatus();
}

}  // namespace premarket::fastpath
