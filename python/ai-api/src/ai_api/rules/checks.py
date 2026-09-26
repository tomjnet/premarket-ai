"""The rule checks: entities, sources and dated text.

Each check returns reason codes plus evidence: plain-text explanations shown
on the news detail page and stored with the result.
"""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses
import datetime
import pathlib
import re

import yaml

from ai_api.dedup import normalize
from ai_api.rules import registry as registry_lib

FAKE_COMPANY = "FAKE_COMPANY"
FAKE_TICKER = "FAKE_TICKER"
SPOOFED_SOURCE = "SPOOFED_SOURCE"
STALE = "STALE"

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_FULL_DATE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r") ([0-9]{1,2}), ([0-9]{4})\b"
)
# Lowercase words that may sit inside a company name ("Bank of America").
_NAME_CONNECTORS = frozenset({"and", "&", "of", "de", "the"})
_NAME_MAX_WORDS = 10
_HOMOGLYPHS = str.maketrans("0134578", "oleasbt")
_MIN_FUZZY_BRAND = 5


@dataclasses.dataclass(frozen=True)
class Evidence:
    """Why a check flagged (or cleared) an item.

    Attributes:
        check: ``entity``, ``source``, ``dedup`` or ``stale``.
        code: The reason code it supports, or None for context.
        message: A plain-text explanation.
    """

    check: str
    code: str | None
    message: str

    def to_json(self) -> dict[str, str | None]:
        """The evidence as stored in ``ai.rule_check.evidence``."""
        return {"check": self.check, "code": self.code, "message": self.message}


@dataclasses.dataclass(frozen=True)
class Finding:
    """Reason codes and evidence of one check on one item."""

    codes: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()


# --- entity check -------------------------------------------------------------


def _is_name_word(word: str) -> bool:
    first = word[:1]
    return first.isupper() or first.isdigit()


def names_before(body: str, ticker: str) -> list[str]:
    """The company names written right before ``(TICKER)`` in the body.

    ``The board of Bank of America Corporation (BAC)`` gives ``Bank of
    America Corporation``: the capitalized words (and connectors such as
    "of") going back from the ticker, without a leading connector.

    Args:
        body: The story (boilerplate removed).
        ticker: The ticker as the vendor wrote it.

    Returns:
        One name per mention; mentions without a name are skipped.
    """
    names = []
    for match in re.finditer(r"\(" + re.escape(ticker) + r"\)", body):
        words = body[: match.start()].split()[-_NAME_MAX_WORDS:]
        taken: list[str] = []
        while words:
            word = words[-1]
            if _is_name_word(word) or (
                taken and word.lower() in _NAME_CONNECTORS
            ):
                taken.insert(0, words.pop())
            else:
                break
        while taken and taken[0].lower() in _NAME_CONNECTORS:
            taken.pop(0)
        if taken:
            names.append(" ".join(taken))
    return names


def _registered_name(name: str, registry: registry_lib.Registry) -> str | None:
    """``name`` or its shortest registered tail ("Shares of Apple Inc.")."""
    words = name.split()
    for start in range(len(words)):
        # A one-word tail ("Group") is too vague to count as a match.
        if len(words) - start < 2 and start > 0:
            break
        if words[start].lower() in _NAME_CONNECTORS:
            continue
        candidate = " ".join(words[start:])
        if registry.has_name(candidate):
            return candidate
    return None


def check_entities(
    tickers: tuple[str, ...],
    body: str,
    registry: registry_lib.Registry | None,
) -> Finding:
    """Hard rules FAKE_TICKER and FAKE_COMPANY against the SEC registry.

    - A ticker the registry doesn't list is FAKE_TICKER.
    - If, in addition, the name written next to it isn't a registered
      company either, the company is invented: FAKE_COMPANY.

    Args:
        tickers: The vendor's tickers for the item.
        body: The story (boilerplate removed).
        registry: The loaded registry; None when it isn't available, in
            which case nothing is flagged.

    Returns:
        The finding.
    """
    if registry is None or len(registry) == 0:
        return Finding(
            evidence=(
                Evidence(
                    "entity",
                    None,
                    "Entity check skipped: the SEC ticker registry isn't "
                    "loaded.",
                ),
            )
        )
    codes: list[str] = []
    evidence: list[Evidence] = []
    about = registry.describe()
    for ticker in tickers:
        company = registry.company(ticker)
        if company is not None:
            evidence.append(
                Evidence(
                    "entity",
                    None,
                    f"{ticker} is {company.title} in the SEC ticker registry.",
                )
            )
            continue
        codes.append(FAKE_TICKER)
        names = names_before(body, ticker)
        real = [
            found
            for found in (_registered_name(n, registry) for n in names)
            if found is not None
        ]
        missing = (
            f"Ticker {ticker} is not in the SEC ticker registry ({about})."
        )
        if real:
            evidence.append(
                Evidence(
                    "entity",
                    FAKE_TICKER,
                    f"{missing} {real[0]} is a registered company, so the "
                    "ticker is wrong.",
                )
            )
        elif names:
            codes.append(FAKE_COMPANY)
            evidence.append(Evidence("entity", FAKE_TICKER, missing))
            evidence.append(
                Evidence(
                    "entity",
                    FAKE_COMPANY,
                    f'No registered company is named "{names[0]}".',
                )
            )
        else:
            evidence.append(Evidence("entity", FAKE_TICKER, missing))
    return Finding(tuple(dict.fromkeys(codes)), tuple(evidence))


# --- source check -------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Reputation:
    """A domain's standing.

    Attributes:
        domain: The domain (lowercase).
        tier: ``trusted``, ``neutral``, ``low`` or ``blocked``.
        reputation: 0.0 (worst) to 1.0.
        note: Why.
    """

    domain: str
    tier: str
    reputation: float
    note: str = ""


def _within_one_edit(a: str, b: str) -> bool:
    """Damerau-Levenshtein distance <= 1 (one typo or swapped pair)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diffs = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        return (
            len(diffs) == 2
            and diffs[1] == diffs[0] + 1
            and a[diffs[0]] == b[diffs[1]]
            and a[diffs[1]] == b[diffs[0]]
        )
    short, long = (a, b) if len(a) < len(b) else (b, a)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


def _fold(label: str) -> str:
    """Undoes common lookalike tricks: 0->o, 1->l, rn->m, vv->w."""
    return label.translate(_HOMOGLYPHS).replace("rn", "m").replace("vv", "w")


def url_host(url: str) -> str | None:
    """The lowercase host of an absolute URL (no user info or port)."""
    try:
        canonical = normalize.canonical_url(url)
    except ValueError:
        return None
    authority = canonical.split("://", 1)[1]
    for mark in "/?":
        authority = authority.split(mark, 1)[0]
    host = authority.rpartition("@")[2]
    if host.startswith("["):
        return host.split("]", 1)[0] + "]"
    return host.split(":", 1)[0]


@dataclasses.dataclass(frozen=True)
class SourcePolicy:
    """Domain reputations and the brands lookalikes imitate.

    Attributes:
        reputations: Known domains.
        brands: Brand name -> its official domains.
    """

    reputations: Mapping[str, Reputation]
    brands: Mapping[str, tuple[str, ...]]

    @classmethod
    def from_yaml(cls, path: pathlib.Path) -> SourcePolicy:
        """Loads ``python/config/sources.yaml``.

        Args:
            path: The file.

        Returns:
            The policy.
        """
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        reputations = {
            str(row["domain"]).lower(): Reputation(
                str(row["domain"]).lower(),
                str(row["tier"]),
                float(row["reputation"]),
                str(row.get("note", "")),
            )
            for row in data.get("reputations", [])
        }
        brands = {
            str(brand).lower(): tuple(str(d).lower() for d in domains)
            for brand, domains in data.get("brands", {}).items()
        }
        return cls(reputations, brands)

    def with_reputations(self, rows: list[Reputation]) -> SourcePolicy:
        """The same brands with reputations from ``ai.source_reputation``."""
        return dataclasses.replace(
            self, reputations={row.domain: row for row in rows}
        )

    def reputation(self, host: str) -> Reputation | None:
        """The reputation of ``host`` or of its closest listed parent."""
        return self._reputation(host.strip().lower())

    def _reputation(self, host: str) -> Reputation | None:
        labels = host.split(".")
        for i in range(len(labels) - 1):
            found = self.reputations.get(".".join(labels[i:]))
            if found is not None:
                return found
        return None

    def _imitated(self, host: str) -> tuple[str, str] | None:
        """(brand, official domain) that ``host`` imitates, or None."""
        for official in self.brands.values():
            if any(host == d or host.endswith("." + d) for d in official):
                return None
        parts = [part for part in re.split(r"[.\-_]", host) if part]
        for brand, official in self.brands.items():
            for part in parts:
                folded = _fold(part)
                if brand in (part, folded) or (
                    len(brand) >= _MIN_FUZZY_BRAND
                    and _within_one_edit(folded, brand)
                ):
                    return brand, official[0]
        return None

    def check(self, source_url: str, source_domain: str) -> Finding:
        """SPOOFED_SOURCE for lookalike or mismatched domains.

        Args:
            source_url: The item's source link.
            source_domain: The domain the vendor says it's from.

        Returns:
            The finding (the reputation is context, not a reason code).
        """
        codes: list[str] = []
        evidence: list[Evidence] = []
        host = url_host(source_url)
        domain = source_domain.strip().lower()
        if host is None:
            codes.append(SPOOFED_SOURCE)
            evidence.append(
                Evidence(
                    "source",
                    SPOOFED_SOURCE,
                    "The source link is not a valid absolute URL.",
                )
            )
            host = domain
        elif domain != host:
            codes.append(SPOOFED_SOURCE)
            evidence.append(
                Evidence(
                    "source",
                    SPOOFED_SOURCE,
                    f"The source domain {domain} doesn't match the link's "
                    f"host {host}.",
                )
            )
        imitated = self._imitated(host)
        if imitated is not None:
            brand, official = imitated
            codes.append(SPOOFED_SOURCE)
            evidence.append(
                Evidence(
                    "source",
                    SPOOFED_SOURCE,
                    f"{host} imitates {brand} (official domain: {official}).",
                )
            )
        reputation = self._reputation(host)
        if reputation is None:
            evidence.append(
                Evidence(
                    "source",
                    None,
                    f"{host} isn't in the source reputation list.",
                )
            )
        else:
            note = f" ({reputation.note})" if reputation.note else ""
            evidence.append(
                Evidence(
                    "source",
                    None,
                    f"{host}: {reputation.tier} source, reputation "
                    f"{reputation.reputation:.2f}{note}.",
                )
            )
        return Finding(tuple(dict.fromkeys(codes)), tuple(evidence))


# --- dated text ---------------------------------------------------------------


def check_dates(
    body: str, feed_date: datetime.date, max_age_days: int
) -> Finding:
    """STALE when the story is dated long before the feed date.

    "On March 3, 2026, Apple announced..." in the 2026-09-24 feed is old
    news presented as new.

    Args:
        body: The story (boilerplate removed).
        feed_date: The feed date.
        max_age_days: Older full dates (Month D, YYYY) are stale.

    Returns:
        The finding.
    """
    oldest = None
    for match in _FULL_DATE.finditer(body):
        month = _MONTHS.index(match.group(1)) + 1
        try:
            day = datetime.date(int(match.group(3)), month, int(match.group(2)))
        except ValueError:
            continue
        if oldest is None or day < oldest[0]:
            oldest = (day, match.group())
    if oldest is None:
        return Finding()
    age = (feed_date - oldest[0]).days
    if age <= max_age_days:
        return Finding()
    return Finding(
        (STALE,),
        (
            Evidence(
                "stale",
                STALE,
                f"The story is dated {oldest[1]}, {age} days before the "
                "feed date, but is sent as today's news.",
            ),
        ),
    )
