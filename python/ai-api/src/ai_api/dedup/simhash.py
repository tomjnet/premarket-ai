"""64-bit SimHash, Hamming distance and band keys (dedup level L2).

The C++ module ``premarket_fastpath`` computes them when installed; the
``ref_*`` functions are the reference the parity tests compare it with.

SimHash: every feature (a word n-gram of the normalized text, words split on
spaces) is hashed to 64 bits with FNV-1a followed by the MurmurHash3 64-bit
finalizer; bit i of the result is 1 when more features have bit i set than
not. Similar texts get hashes a small Hamming distance apart.

Bands: the 64 bits are cut into ``bands`` consecutive slices from the lowest
bit up (the first ``64 % bands`` slices are one bit wider). Two hashes at
most ``bands - 1`` bits apart are equal in at least one slice (pigeonhole),
so looking up each slice finds every candidate.
"""

from __future__ import annotations

from ai_api.dedup import fastpath

HASH_BITS = 64
MAX_NGRAM = 8
_MASK64 = (1 << HASH_BITS) - 1
_FNV_OFFSET = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3


def _fmix64(value: int) -> int:
    value ^= value >> 33
    value = (value * 0xFF51AFD7ED558CCD) & _MASK64
    value ^= value >> 33
    value = (value * 0xC4CEB9FE1A85EC53) & _MASK64
    value ^= value >> 33
    return value


def ref_feature_hash(data: bytes) -> int:
    """FNV-1a 64 of ``data``, then the MurmurHash3 finalizer."""
    value = _FNV_OFFSET
    for byte in data:
        value ^= byte
        value = (value * _FNV_PRIME) & _MASK64
    return _fmix64(value)


def _check_ngram(ngram: int) -> None:
    if not 1 <= ngram <= MAX_NGRAM:
        raise ValueError(f"ngram must be in [1, {MAX_NGRAM}], got {ngram}")


def ref_simhash64(text: str, ngram: int = 2) -> int:
    """Reference of the C++ ``simhash64``.

    Args:
        text: Normalized text. Words are split on spaces; empty words are
            skipped.
        ngram: Words per feature, 1 to 8. A text with fewer words than
            ``ngram`` is one feature.

    Returns:
        The SimHash as an unsigned 64-bit integer; 0 for a text without
        words.

    Raises:
        ValueError: ``ngram`` is out of range.
    """
    _check_ngram(ngram)
    words = [word for word in text.split(" ") if word]
    if not words:
        return 0
    count = max(1, len(words) - ngram + 1)
    weights = [0] * HASH_BITS
    for i in range(count):
        feature = " ".join(words[i : i + ngram]).encode()
        value = ref_feature_hash(feature)
        for bit in range(HASH_BITS):
            weights[bit] += 1 if (value >> bit) & 1 else -1
    return sum(1 << bit for bit in range(HASH_BITS) if weights[bit] > 0)


def ref_hamming(a: int, b: int) -> int:
    """Reference of the C++ ``hamming``: bits that differ."""
    return (a ^ b).bit_count()


def ref_band_keys(value: int, bands: int) -> list[int]:
    """Reference of the C++ ``band_keys``.

    Args:
        value: A 64-bit hash.
        bands: The number of slices, 1 to 64.

    Returns:
        The value of each slice, lowest bits first.

    Raises:
        ValueError: ``bands`` is out of range.
    """
    if not 1 <= bands <= HASH_BITS:
        raise ValueError(f"bands must be in [1, {HASH_BITS}], got {bands}")
    base, extra = divmod(HASH_BITS, bands)
    keys = []
    shift = 0
    for i in range(bands):
        width = base + (1 if i < extra else 0)
        keys.append((value >> shift) & ((1 << width) - 1))
        shift += width
    return keys


def simhash64(text: str, ngram: int = 2) -> int:
    """See ``ref_simhash64`` (in C++ when available)."""
    native = fastpath.module()
    if native is None:
        return ref_simhash64(text, ngram)
    return native.simhash64(text, ngram)


def hamming(a: int, b: int) -> int:
    """See ``ref_hamming`` (in C++ when available)."""
    native = fastpath.module()
    if native is None:
        return ref_hamming(a, b)
    return native.hamming(a, b)


def band_keys(value: int, bands: int) -> list[int]:
    """See ``ref_band_keys`` (in C++ when available)."""
    native = fastpath.module()
    if native is None:
        return ref_band_keys(value, bands)
    return native.band_keys(value, bands)
