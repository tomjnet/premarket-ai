// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// Expected values come from the Python reference (ref_canonical_url in
// python/ai-api/src/ai_api/dedup/normalize.py).

#include "fastpath/url.h"

#include <string>
#include <string_view>

#include "absl/status/status.h"
#include "gtest/gtest.h"

namespace premarket::fastpath {
namespace {

std::string Canonical(std::string_view url) {
  std::string out;
  const absl::Status status = CanonicalUrl(url, &out);
  EXPECT_TRUE(status.ok()) << url << ": " << status;
  return out;
}

bool Rejected(std::string_view url) {
  std::string out;
  const absl::Status status = CanonicalUrl(url, &out);
  return absl::IsInvalidArgument(status);
}

TEST(CanonicalUrlTest, DocstringExample) {
  EXPECT_EQ(Canonical("https://a.example/x?utm_source=y"),
            "https://a.example/x");
}

TEST(CanonicalUrlTest, LowercasesSchemeAndHostDropsDefaultPortAndTracking) {
  EXPECT_EQ(Canonical("HTTPS://Www.Example.COM:443/Path/?b=2&utm_source=x"
                      "&a=1&UTM_Medium=y&ref=z#frag"),
            "https://www.example.com/Path?a=1&b=2");
}

TEST(CanonicalUrlTest, KeepsUserInfoCase) {
  EXPECT_EQ(Canonical("http://User:Pw@Host:80//"), "http://User:Pw@host");
  EXPECT_EQ(Canonical("http://a@b@Host/"), "http://a@b@host");
}

TEST(CanonicalUrlTest, Ports) {
  EXPECT_EQ(Canonical("http://h:/p"), "http://h/p");
  EXPECT_EQ(Canonical("ftp://h:80/"), "ftp://h:80");
  EXPECT_EQ(Canonical("http://h:443"), "http://h:443");
  EXPECT_EQ(Canonical("HTTP://h:80"), "http://h");
  EXPECT_EQ(Canonical("http://h:x:80"), "http://h:x");
}

TEST(CanonicalUrlTest, Ipv6) {
  EXPECT_EQ(Canonical("https://[::1]:8443/x"), "https://[::1]:8443/x");
  EXPECT_EQ(Canonical("https://[::1]:443"), "https://[::1]");
  EXPECT_EQ(Canonical("https://[::1]abc"), "https://[::1]abc");
  EXPECT_EQ(Canonical("https://[::1"), "https://[::1");
  EXPECT_EQ(Canonical("https://[::1]:8:9"), "https://[::1]:8:9");
  EXPECT_EQ(Canonical("https://[AB]"), "https://[ab]");
}

TEST(CanonicalUrlTest, Query) {
  EXPECT_EQ(Canonical("https://h?&&b&a&FbClId=1&gclid"), "https://h?a&b");
  EXPECT_EQ(Canonical("https://h/p?c=%41&ref_src=x&refs=1"),
            "https://h/p?c=%41&refs=1");
  EXPECT_EQ(Canonical("https://h/?utm_=1&igshid&mc_cid=2&mc_eid=3"),
            "https://h");
  EXPECT_EQ(Canonical("https://h/p?"), "https://h/p");
  EXPECT_EQ(Canonical("https://h/p?b?=1&a"), "https://h/p?a&b?=1");
}

TEST(CanonicalUrlTest, PathAndFragment) {
  EXPECT_EQ(Canonical("  https://h/a/b/  "), "https://h/a/b");
  EXPECT_EQ(Canonical("https://h#x?y"), "https://h");
  EXPECT_EQ(Canonical("https://h/A//"), "https://h/A");
}

TEST(CanonicalUrlTest, SchemeCharacters) {
  EXPECT_EQ(Canonical("a+b.c-d://H"), "a+b.c-d://h");
}

TEST(CanonicalUrlTest, Rejects) {
  EXPECT_TRUE(Rejected(""));
  EXPECT_TRUE(Rejected("1http://h"));
  EXPECT_TRUE(Rejected("http//h"));
  EXPECT_TRUE(Rejected("://h"));
  EXPECT_TRUE(Rejected("ht tp://h"));
  EXPECT_TRUE(Rejected("https://"));
  EXPECT_TRUE(Rejected("https://u@:80/"));
  EXPECT_TRUE(Rejected("https:///path"));
  EXPECT_TRUE(Rejected("https://#h"));
}

}  // namespace
}  // namespace premarket::fastpath
