"""Duplicate-check settings, read from the environment.

The defaults were measured on vendor-sim data (10 days, seed 42): a one-word
edit moves a 64-bit SimHash of word bigrams by 1 to 8 bits, while unrelated
stories of the same template can be as close as 3 bits. So SimHash only
finds candidates (Hamming <= 10, looked up in 11 bands); a candidate is a
near duplicate only if its tickers and key numbers are the same and at most
3 words differ.

L3 (increment 3, ``paraphrase``) was measured the same way with
``nomic-embed-text``: paraphrases score cosine 0.919 to 0.982, but so do
stories of the same template with one detail changed ("payment" vs
"billing" systems). Those differ in only 4 to 8 words, while the vendor's
paraphrases reword 23 to 53. So a paraphrase needs cosine >= 0.90, the same
tickers and key numbers, and at least 10 differing words; a closer text is
a conflicting version, not a copy.
"""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses

from ai_api.dedup import simhash

_DAY_S = 86_400


def _int(
    env: Mapping[str, str], name: str, default: int, low: int, high: int
) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from e
    if not low <= value <= high:
        raise ValueError(f"{name} must be in [{low}, {high}], got {value}")
    return value


def _float(
    env: Mapping[str, str],
    name: str,
    default: float,
    low: float,
    high: float,
) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be a number, got {raw!r}") from e
    if not low <= value <= high:
        raise ValueError(f"{name} must be in [{low}, {high}], got {value}")
    return value


@dataclasses.dataclass(frozen=True)
class DedupConfig:
    """Thresholds of the duplicate check.

    Attributes:
        window_days: How many feed days back a story counts as a duplicate
            (DEDUP_WINDOW_DAYS). Older copies are new stories again.
        simhash_ngram: Words per SimHash feature (DEDUP_SIMHASH_NGRAM).
        simhash_max_hamming: Largest Hamming distance of a near-duplicate
            candidate (DEDUP_SIMHASH_MAX_HAMMING).
        near_max_word_edits: Most words that may differ between near
            duplicates, counted as a multiset difference, so reordered
            sentences cost nothing (DEDUP_NEAR_MAX_WORD_EDITS).
        cosine_min: Smallest embedding cosine of an L3 paraphrase, and of
            a conflicting version (DEDUP_COSINE_MIN).
        paraphrase_min_word_edits: Fewest differing words of an L3
            paraphrase; a closer text with other details is a conflicting
            version (DEDUP_PARAPHRASE_MIN_WORD_EDITS).
    """

    window_days: int = 7
    simhash_ngram: int = 2
    simhash_max_hamming: int = 10
    near_max_word_edits: int = 3
    cosine_min: float = 0.90
    paraphrase_min_word_edits: int = 10

    @property
    def bands(self) -> int:
        """Band count that finds every candidate within the Hamming limit."""
        return self.simhash_max_hamming + 1

    @property
    def ttl_s(self) -> int:
        """Lifetime of the Redis keys: the window plus one day."""
        return (self.window_days + 1) * _DAY_S

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> DedupConfig:
        """Reads the DEDUP_* variables; missing ones keep the defaults.

        Args:
            env: The environment.

        Returns:
            The settings.

        Raises:
            ValueError: A value isn't an integer or is out of range.
        """
        return cls(
            window_days=_int(env, "DEDUP_WINDOW_DAYS", 7, 1, 60),
            simhash_ngram=_int(
                env, "DEDUP_SIMHASH_NGRAM", 2, 1, simhash.MAX_NGRAM
            ),
            simhash_max_hamming=_int(
                env, "DEDUP_SIMHASH_MAX_HAMMING", 10, 0, simhash.HASH_BITS - 1
            ),
            near_max_word_edits=_int(
                env, "DEDUP_NEAR_MAX_WORD_EDITS", 3, 0, 50
            ),
            cosine_min=_float(env, "DEDUP_COSINE_MIN", 0.90, 0.5, 1.0),
            paraphrase_min_word_edits=_int(
                env, "DEDUP_PARAPHRASE_MIN_WORD_EDITS", 10, 0, 500
            ),
        )
