"""premarket_fastpath (C++20) must match the Python reference exactly.

Hypothesis feeds both implementations random input, biased towards the
characters each function cares about. In the ai-api image the module is
required (PREMARKET_FASTPATH=required), so these tests never silently skip
there.
"""

import os

from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st
import pytest

from ai_api.dedup import fastpath
from ai_api.dedup import normalize
from ai_api.dedup import simhash

_REQUIRED = os.environ.get("PREMARKET_FASTPATH", "") == "required"
native = fastpath.module()

pytestmark = pytest.mark.skipif(
    native is None and not _REQUIRED,
    reason="premarket_fastpath is not installed",
)

_SETTINGS = settings(max_examples=2000, deadline=None)
_TEXT_ALPHABET = st.sampled_from(
    list("aAzZ09 <>/!?&;#$%,.-_:=@[]\t\n\r\f\v")
    + ["&amp;", "&lt;", "&gt;", "&quot;", "&#39;", "&apos;", "&nbsp;"]
    + ["\u00ad", "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"]
    + ["é", "Ä", "ß", "İ", "\u00a0", "日", "😀", "Ｖ"]
)
_texts = st.one_of(
    st.text(),
    st.lists(_TEXT_ALPHABET, max_size=60).map("".join),
)
_URL_PART = st.sampled_from(
    list("aZ09-._~%/?#&=:@[]")
    + ["utm_source=x", "UTM_Medium=y", "ref=z", "fbclid=1", "gclid", "a=1"]
    + ["HTTP://", "https://", "Www.Example.COM", ":80", ":443", ":", "é"]
)
_urls = st.one_of(
    st.text(),
    st.lists(_URL_PART, max_size=25).map("".join),
    st.lists(_URL_PART, max_size=20).map(lambda p: "https://" + "".join(p)),
)
_FACT_PART = st.sampled_from(
    list("0123456789$%,. ab-")
    + ["march", "may", "one", "twelve", "(two)", "june,", " "]
)
_fact_texts = st.one_of(
    st.text(),
    st.lists(_FACT_PART, max_size=40).map("".join),
)
_words = st.lists(
    st.sampled_from(["a", "b", "rose", "12%", "$3.5", "日本", "", " "]),
    max_size=40,
).map(" ".join)


def _native():
    assert native is not None, "premarket_fastpath is required here"
    return native


def test_required_module_is_installed():
    if _REQUIRED:
        assert native is not None
        assert fastpath.backend() == "native"


@_SETTINGS
@given(_texts)
def test_normalize_text(text):
    assert _native().normalize_text(text) == normalize.ref_normalize_text(text)


@_SETTINGS
@given(_urls)
def test_canonical_url(url):
    try:
        expected = normalize.ref_canonical_url(url)
    except ValueError:
        with pytest.raises(ValueError):
            _native().canonical_url(url)
        return
    assert _native().canonical_url(url) == expected


@_SETTINGS
@given(_texts)
def test_sha256(text):
    assert _native().sha256(text) == normalize.ref_sha256(text)


@_SETTINGS
@given(_fact_texts)
def test_extract_key_numbers(text):
    expected = normalize.ref_extract_key_numbers(text)
    assert _native().extract_key_numbers(text) == expected


@_SETTINGS
@given(st.one_of(_words, _texts), st.integers(min_value=1, max_value=8))
def test_simhash64(text, ngram):
    assert _native().simhash64(text, ngram) == simhash.ref_simhash64(
        text, ngram
    )


@_SETTINGS
@given(st.integers(0, 2**64 - 1), st.integers(0, 2**64 - 1))
def test_hamming(a, b):
    assert _native().hamming(a, b) == simhash.ref_hamming(a, b)


@_SETTINGS
@given(st.integers(0, 2**64 - 1), st.integers(min_value=1, max_value=64))
def test_band_keys(value, bands):
    assert _native().band_keys(value, bands) == simhash.ref_band_keys(
        value, bands
    )


@pytest.mark.parametrize("bad", [0, 65, -1])
def test_band_keys_rejects_bad_counts(bad):
    with pytest.raises(ValueError):
        _native().band_keys(1, bad)


@pytest.mark.parametrize("bad", [0, 9])
def test_simhash_rejects_bad_ngram(bad):
    with pytest.raises(ValueError):
        _native().simhash64("a b", bad)


def test_dispatch_uses_the_native_module():
    text = "NVIDIA <b>reports</b> Q3 revenue of $35.1B, up 94%"
    normalized = normalize.normalize_text(text)
    assert normalized == "nvidia reports q3 revenue of $35.1b, up 94%"
    assert simhash.simhash64(normalized) == simhash.ref_simhash64(normalized)
