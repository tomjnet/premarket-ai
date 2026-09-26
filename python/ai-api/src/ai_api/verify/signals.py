"""Deterministic text signals of the verify graph (no model, no network).

- ``headline_numbers``: amounts and percentages in the headline that the
  body never states: "revenue soars 120%" over a body that says 12%
  (NUMBER_MISMATCH).
- ``sensational``: hype words, shouting and exclamation marks in the
  headline (SENSATIONAL_HEADLINE).
- ``material_event``: the kinds of news a US issuer must file an 8-K for
  within four business days (a deal, an executive leaving, a breakup, a
  halt, a bankruptcy, a regulator's decision), so a real one leaves a
  primary source.
- ``price_moves``: "shares rose 20%" claims, checked against prices.
- ``content_words``: the words two reports of one story share.
"""

from __future__ import annotations

import dataclasses
import re

_NUMBER = r"(\d+(?:,\d{3})*(?:\.\d+)?)"
_PERCENT = re.compile(_NUMBER + r"\s?(?:%|percent\b)", re.IGNORECASE)
_AMOUNT = re.compile(
    r"\$\s?" + _NUMBER + r"\s?(billion|bn|b|million|mn|m|trillion|tn|t)?\b",
    re.IGNORECASE,
)
_SCALE = {
    "t": 1e12,
    "tn": 1e12,
    "trillion": 1e12,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
}
_HYPE = re.compile(
    r"\b(explod\w*|skyrocket\w*|soar\w*|blowout|shock\w*|stunning|"
    r"jaw[- ]dropping|insane|mind[- ]blowing|to the moon|moonshot|"
    r"massive gains?|once[- ]in[- ]a[- ]lifetime|you won'?t believe|"
    r"set to (?:explode|soar|skyrocket|double|triple))\b",
    re.IGNORECASE,
)
# Upper-case words that are normal in a headline.
_ACRONYMS = frozenset(
    {
        "CEO",
        "CFO",
        "COO",
        "CTO",
        "FDA",
        "SEC",
        "IPO",
        "EPS",
        "AI",
        "US",
        "USA",
        "UK",
        "EU",
        "ETF",
        "GDP",
        "CPI",
        "FED",
        "NYSE",
        "EV",
        "M&A",
        "R&D",
        "Q1",
        "Q2",
        "Q3",
        "Q4",
        "SYNTHETIC",
    }
)
_SHOUT = re.compile(r"\b[A-Z]{4,}\b")
_MATERIAL = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(to be acquired|acquir(e|es|ed|ing)|acquisition|merger|takeover|"
        r"buyout|all-cash deal)\b",
        r"\b(resign(s|ed|ing)?|step(s|ped)? down|ousted|fired)\b",
        r"\b(split the company|break ?up|spin[- ]?off|separate (listed )?"
        r"(companies|businesses))\b",
        r"\b(halt(s|ed)?|stop(s|ped)|suspend(s|ed)?) (all )?operations\b",
        r"\b(bankruptcy|chapter 11|insolven\w+|default(s|ed)? on)\b",
        r"\b(regulators?|fda) (approv\w+|reject\w+)|\bwins? fda approval\b",
        r"\b(inquiry|probe|investigation|subpoena|fraud)\b",
        r"\b(supply|multi-year) contract\b",
    )
)
_PRICE_MOVE = re.compile(
    r"\b(?:shares|stock)\b[^.]{0,40}?\b(rose|jumped|gained|climbed|soared|"
    r"surged|rallied|fell|dropped|slid|plunged|sank|tumbled|lost)\s+(?:by\s+)?"
    + _NUMBER
    + r"\s?%",
    re.IGNORECASE,
)
_DOWN_WORDS = frozenset(
    {"fell", "dropped", "slid", "plunged", "sank", "tumbled", "lost"}
)
_WORD = re.compile(r"[a-z][a-z'-]+")
_STOP_WORDS = frozenset(
    (
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "has", "have", "in", "into", "is", "it", "its", "of", "on", "or",
        "over", "said", "says", "that", "the", "their", "this", "to", "was",
        "were", "will", "with", "after", "amid", "about", "than", "more",
        "new", "up", "down", "per", "year", "quarter", "company",
        "companies",
    )
)  # fmt: skip
_AMOUNT_TOLERANCE = 0.005


def _float(text: str) -> float:
    return float(text.replace(",", ""))


def percentages(text: str) -> set[float]:
    """Every percentage the text states ("12%", "12 percent")."""
    return {_float(m.group(1)) for m in _PERCENT.finditer(text)}


def amounts(text: str) -> set[float]:
    """Every dollar amount the text states, in dollars ("$85.1B")."""
    found = set()
    for match in _AMOUNT.finditer(text):
        unit = (match.group(2) or "").lower()
        found.add(_float(match.group(1)) * _SCALE.get(unit, 1.0))
    return found


def _has_amount(value: float, others: set[float]) -> bool:
    return any(
        abs(value - other) <= _AMOUNT_TOLERANCE * max(value, other)
        for other in others
    )


def headline_numbers(headline: str, body: str) -> list[str]:
    """Headline numbers the body doesn't state.

    Args:
        headline: The headline.
        body: The story.

    Returns:
        The missing numbers, as text ("120%", "$4.5B"); empty when every
        headline number is in the body.
    """
    missing = []
    body_percentages = percentages(body)
    for value in sorted(percentages(headline)):
        if value not in body_percentages:
            missing.append(f"{value:g}%")
    body_amounts = amounts(body)
    for value in sorted(amounts(headline)):
        if not _has_amount(value, body_amounts):
            missing.append(f"${value:,.0f}")
    return missing


def sensational(headline: str, body: str = "") -> list[str]:
    """Hype phrases, shouted words and exclamation marks in a headline.

    Args:
        headline: The headline.
        body: The story: an upper-case word it also uses (a name such as
            NVIDIA) isn't shouting.

    Returns:
        The phrases found; empty for a sober headline.
    """
    hits = [m.group() for m in _HYPE.finditer(headline)]
    body_words = set(_SHOUT.findall(body))
    hits += [
        word
        for word in _SHOUT.findall(headline)
        if word not in _ACRONYMS and word not in body_words
    ]
    if "!" in headline:
        hits.append("!")
    return hits


def material_event(text: str) -> list[str]:
    """Phrases that make a story a material event (see module docstring)."""
    return [m.group() for pattern in _MATERIAL for m in pattern.finditer(text)]


@dataclasses.dataclass(frozen=True)
class PriceMove:
    """A claimed share-price move.

    Attributes:
        percent: The size of the move, positive.
        down: True for a fall.
        text: The claim as written.
    """

    percent: float
    down: bool
    text: str


def price_moves(text: str) -> list[PriceMove]:
    """Claims such as "shares rose 20%" in the text."""
    return [
        PriceMove(
            _float(m.group(2)), m.group(1).lower() in _DOWN_WORDS, m.group()
        )
        for m in _PRICE_MOVE.finditer(text)
    ]


def content_words(text: str) -> set[str]:
    """Lower-case words that carry the story (no stop words)."""
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP_WORDS} - {
        "synthetic"
    }


def overlap(story: str, other: str) -> float:
    """Share of the story's content words that ``other`` contains."""
    words = content_words(story)
    if not words:
        return 0.0
    return len(words & content_words(other)) / len(words)
