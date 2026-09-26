"""SimHash, Hamming distance and band keys (shared by both backends)."""

import pytest

from ai_api.dedup import normalize
from ai_api.dedup import simhash

_STORY = normalize.normalize_text(
    "Apple reports Q3 revenue of $85.1B, up 12% from a year ago. Apple Inc. "
    "(AAPL) said revenue for its fiscal Q3 reached $85.1 billion, up 12% "
    "from a year earlier. Earnings per share were $1.40. Management will "
    "discuss the results on its scheduled conference call."
)


def test_one_word_edit_stays_close_and_other_stories_are_far():
    near = _STORY.replace(" said ", " stated ", 1)
    other = normalize.normalize_text(
        "Exxon Mobil raises quarterly dividend to $1.02 per share. The board "
        "of Exxon Mobil Corporation (XOM) approved a quarterly dividend of "
        "$1.02 per share, payable next month to shareholders of record."
    )
    base = simhash.simhash64(_STORY)
    assert simhash.hamming(base, simhash.simhash64(near)) <= 10
    assert simhash.hamming(base, simhash.simhash64(other)) > 10


def test_empty_and_short_texts():
    assert simhash.simhash64("") == 0
    assert simhash.simhash64("   ") == 0
    # Fewer words than the n-gram size: one feature, the whole text.
    one = simhash.ref_feature_hash(b"solo")
    assert simhash.simhash64("solo", 2) == one
    assert simhash.simhash64("a  b", 1) == simhash.simhash64("a b", 1)


def test_feature_hash_is_fnv1a_with_the_murmur_finalizer():
    # FNV-1a 64 of the empty input is the offset basis.
    assert simhash.ref_feature_hash(b"") == simhash._fmix64(0xCBF29CE484222325)


@pytest.mark.parametrize("bad", [0, 9])
def test_ngram_range(bad):
    with pytest.raises(ValueError):
        simhash.simhash64("a b c", bad)


def test_band_keys_cover_all_64_bits():
    value = (1 << 64) - 1
    keys = simhash.band_keys(value, 11)
    widths = [key.bit_length() for key in keys]
    assert widths == [6] * 9 + [5] * 2
    assert sum(widths) == 64
    assert simhash.band_keys(0x1234, 1) == [0x1234]
    assert simhash.band_keys(value, 64) == [1] * 64


def test_close_hashes_share_a_band():
    """Pigeonhole: 10 flipped bits leave at least one of 11 bands intact."""
    base = simhash.simhash64(_STORY)
    flipped = base
    for bit in range(0, 60, 6):
        flipped ^= 1 << bit
    assert simhash.hamming(base, flipped) == 10
    shared = [
        a == b
        for a, b in zip(
            simhash.band_keys(base, 11),
            simhash.band_keys(flipped, 11),
            strict=True,
        )
    ]
    assert any(shared)


@pytest.mark.parametrize("bad", [0, 65])
def test_band_count_range(bad):
    with pytest.raises(ValueError):
        simhash.band_keys(1, bad)
