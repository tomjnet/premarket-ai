"""The fan-out checks of ``verify_news`` (code calls the tools).

Each check reads the item's structured fields, calls the read-only tools
it needs, and returns a ``Finding`` plus the data the policy uses. A tool
that fails never decides anything: its check records "unavailable" and
the policy sees no evidence either way.

- ``entity_check``: the SEC registry (``lookup_company``); FAKE_COMPANY and
  FAKE_TICKER stay the rule engine's decision (it also checks the name).
- ``source_check``: the reputation table (``get_source_reputation``);
  SPOOFED_SOURCE is the rule engine's.
- ``corroboration``: SEC filings of the week before (``search_news`` on
  the trusted corpus) and the web (``web_search``, counted and linked,
  never stored).
- ``claim_check``: headline numbers against the body, and share-price
  claims against prices (``get_price_history``).
- ``style_signals``: a sensational headline.
- ``fabricated``: a material event from a low-reputation or unknown source
  that no filing and no other outlet reports (after the others).
"""

from __future__ import annotations

from collections.abc import Sequence
import dataclasses
import datetime
import logging
from typing import Any
import urllib.parse

from ai_api.dedup import normalize
from ai_api.verify import evidence as ev
from ai_api.verify import signals
from ai_api.verify import tools as tools_lib

_log = logging.getLogger(__name__)
FILING_WINDOW_DAYS = 7
FILING_SOURCES = frozenset({"edgar_8k", "edgar_ex99"})
_MIN_OVERLAP = 0.5
_MAX_TICKERS = 3
_MAX_LINKS = 3
_PRICE_DAYS = 10
# A claimed move is contradicted when the largest real daily move is under
# half of it (and the claim is at least this big).
_MIN_CHECKED_MOVE = 5.0
_UNTRUSTED_TIERS = frozenset({"low", "blocked", "unknown"})
# The company doesn't exist: there is nothing to search for.
_NO_COMPANY_CODES = frozenset({"FAKE_COMPANY", "FAKE_TICKER"})


@dataclasses.dataclass(frozen=True)
class Item:
    """The fields of one vendor item the checks read.

    Attributes:
        news_id: The ``ai.news_item`` id.
        feed_date: The feed date.
        vendor_item_id: The vendor's id.
        headline: The headline (sanitized).
        body: The story (sanitized, no vendor boilerplate).
        source_url: The source link.
        source_domain: The domain the vendor names.
        tickers: The tickers the vendor tagged.
        rule_codes: The rule engine's reason codes.
        company_names: Names the AI run extracted, by ticker.
    """

    news_id: int
    feed_date: datetime.date
    vendor_item_id: str
    headline: str
    body: str
    source_url: str
    source_domain: str
    tickers: tuple[str, ...]
    rule_codes: tuple[str, ...] = ()
    company_names: dict[str, str] = dataclasses.field(default_factory=dict)

    @property
    def no_company(self) -> bool:
        """The rules found no such company or ticker (nothing to search)."""
        return bool(set(self.rule_codes) & _NO_COMPANY_CODES)

    @property
    def domain(self) -> str:
        """The link's host (or the named domain)."""
        host = urllib.parse.urlsplit(self.source_url).hostname
        return (host or self.source_domain).lower()


@dataclasses.dataclass(frozen=True)
class EntityResult:
    """The entity check.

    Attributes:
        finding: Its evidence (codes come from the rules).
        names: Registered company name by ticker.
        rank: The first ticker's rank in the lab universe, or None.
    """

    finding: ev.Finding
    names: dict[str, str]
    rank: int | None


@dataclasses.dataclass(frozen=True)
class SourceResult:
    """The source check: its evidence and the domain's tier."""

    finding: ev.Finding
    tier: str


@dataclasses.dataclass(frozen=True)
class CorroborationResult:
    """The corroboration check.

    Attributes:
        finding: Its evidence (links to filings and outlets).
        primary_source: An SEC filing reports the story.
        independent_sources: Other trusted or neutral outlets that do.
        searched: The searches ran (False: tools unavailable or skipped).
    """

    finding: ev.Finding
    primary_source: bool = False
    independent_sources: int = 0
    searched: bool = False


async def entity_check(tools: tools_lib.Tools, item: Item) -> EntityResult:
    """Looks each ticker up in the SEC registry (see module docstring)."""
    evidence = []
    names: dict[str, str] = {}
    rank = None
    for i, ticker in enumerate(item.tickers[:_MAX_TICKERS]):
        try:
            found = await tools.lookup_company(ticker)
        except tools_lib.ToolError as e:
            evidence.append(
                ev.Evidence(
                    "entity",
                    None,
                    f"The company lookup for {ticker} is unavailable ({e}).",
                    "registry",
                )
            )
            continue
        if i == 0:
            rank = found.get("rank")
        if found.get("found"):
            names[ticker] = str(found.get("name", ""))
            place = ""
            if found.get("rank") is not None:
                place = f"; number {found['rank'] + 1} in the lab universe"
            evidence.append(
                ev.Evidence(
                    "entity",
                    None,
                    f"SEC registry: {ticker} is {found.get('name')} (CIK "
                    f"{found.get('cik')}){place}.",
                    "registry",
                )
            )
        elif found.get("registry", True):
            evidence.append(
                ev.Evidence(
                    "entity",
                    "FAKE_TICKER" if "FAKE_TICKER" in item.rule_codes else None,
                    f"SEC registry: no listed company has the ticker {ticker}.",
                    "registry",
                )
            )
    return EntityResult(ev.Finding((), tuple(evidence)), names, rank)


async def source_check(tools: tools_lib.Tools, item: Item) -> SourceResult:
    """The source's reputation tier (see module docstring)."""
    domain = item.domain
    try:
        found = await tools.source_reputation(domain)
    except tools_lib.ToolError as e:
        message = f"The reputation lookup for {domain} is unavailable ({e})."
        return SourceResult(
            ev.Finding((), (ev.Evidence("source", None, message),)),
            "unknown",
        )
    tier = str(found.get("tier") or "unknown")
    if tier == "unknown":
        message = f"{domain} is not in the source reputation list."
    else:
        note = f" ({found['note']})" if found.get("note") else ""
        message = (
            f"{domain}: {tier} source, reputation "
            f"{float(found.get('reputation') or 0):.2f}{note}."
        )
    evidence = ev.Evidence("source", None, message, "reputation")
    return SourceResult(ev.Finding((), (evidence,)), tier)


def _headline_query(item: Item, name: str | None) -> str:
    headline = item.headline.replace("[SYNTHETIC]", "").strip()
    if name and name.split()[0].lower() not in headline.lower():
        return f"{name} {headline}"
    return headline


def _reports_story(item: Item, text: str) -> bool:
    """True when ``text`` reports the item's story (words and numbers)."""
    headline = item.headline.replace("[SYNTHETIC]", "")
    if signals.overlap(headline, text) < _MIN_OVERLAP:
        return False
    numbers = set(normalize.extract_key_numbers(headline))
    return numbers <= set(normalize.extract_key_numbers(text))


async def _filings(
    tools: tools_lib.Tools, item: Item, query: str
) -> tuple[list[ev.Evidence], bool]:
    ticker = item.tickers[0] if item.tickers else None
    try:
        hits = await tools.search_filings(
            query, ticker, item.feed_date, FILING_WINDOW_DAYS
        )
    except tools_lib.ToolError as e:
        message = f"The SEC filing search is unavailable ({e})."
        return [ev.Evidence("corroboration", None, message, "filing")], False
    first = item.feed_date - datetime.timedelta(days=FILING_WINDOW_DAYS)
    matches = []
    for hit in hits:
        published = str(hit.get("published_at") or "")[:10]
        if hit.get("source") not in FILING_SOURCES or not published:
            continue
        day = datetime.date.fromisoformat(published)
        if first <= day <= item.feed_date and _reports_story(
            item, str(hit.get("text", ""))
        ):
            matches.append(hit)
    if not matches:
        who = f"{ticker}'s" if ticker else "the company's"
        message = (
            f"No SEC filing of {who} from the {FILING_WINDOW_DAYS} days before "
            f"{item.feed_date.isoformat()} reports this story."
        )
        return [ev.Evidence("corroboration", None, message, "filing")], True
    found = [
        ev.Evidence(
            "corroboration",
            None,
            f"A primary source reports it: {hit.get('title', 'SEC filing')} "
            f"({str(hit.get('published_at'))[:10]}).",
            "filing",
            url=hit.get("url"),
            title=hit.get("title"),
        )
        for hit in matches[:_MAX_LINKS]
    ]
    return found, True


async def _web(
    tools: tools_lib.Tools, item: Item, query: str, name: str | None
) -> tuple[list[ev.Evidence], int, bool]:
    try:
        results = await tools.web_search(query)
    except tools_lib.ToolError as e:
        message = f"The web search is unavailable ({e})."
        return [ev.Evidence("corroboration", None, message, "web")], 0, False
    tiers: dict[str, str] = {}
    outlets: dict[str, dict[str, Any]] = {}
    short = (name or "").split()[0].lower() if name else ""
    for result in results:
        domain = str(result.get("domain") or "").lower()
        if not domain or domain == item.domain or domain in outlets:
            continue
        text = f"{result.get('title', '')} {result.get('snippet', '')}"
        if short and short not in text.lower():
            continue
        if not _reports_story(item, text):
            continue
        if domain not in tiers:
            try:
                reputation = await tools.source_reputation(domain)
                tiers[domain] = str(reputation.get("tier") or "unknown")
            except tools_lib.ToolError:
                tiers[domain] = "unknown"
        if tiers[domain] in ("low", "blocked"):
            continue
        outlets[domain] = result
    if not outlets:
        message = (
            f"Web search ({len(results)} results): no other outlet reports "
            "this story."
        )
        return [ev.Evidence("corroboration", None, message, "web")], 0, True
    found = [
        ev.Evidence(
            "corroboration",
            None,
            f"{domain} reports it too.",
            "web",
            url=result.get("url"),
            title=result.get("title"),
        )
        for domain, result in list(outlets.items())[:_MAX_LINKS]
    ]
    return found, len(outlets), True


async def corroboration(
    tools: tools_lib.Tools, item: Item, names: dict[str, str]
) -> CorroborationResult:
    """Filings and the web (see module docstring)."""
    if item.no_company:
        message = (
            "Not searched: the company or ticker doesn't exist (a hard "
            "rule already decides this item)."
        )
        return CorroborationResult(
            ev.Finding((), (ev.Evidence("corroboration", None, message),))
        )
    ticker = item.tickers[0] if item.tickers else None
    name = names.get(ticker or "") or item.company_names.get(ticker or "")
    query = _headline_query(item, name)
    filings, filings_ran = await _filings(tools, item, query)
    web, outlets, web_ran = await _web(tools, item, query, name)
    primary = any(e.url for e in filings)
    return CorroborationResult(
        ev.Finding((), tuple(filings + web)),
        primary_source=primary,
        independent_sources=outlets,
        searched=filings_ran and web_ran,
    )


async def claim_check(tools: tools_lib.Tools, item: Item) -> ev.Finding:
    """Headline numbers and share-price claims (see module docstring)."""
    codes = []
    evidence = []
    missing = signals.headline_numbers(item.headline, item.body)
    if missing:
        codes.append(ev.NUMBER_MISMATCH)
        stated = sorted(f"{p:g}%" for p in signals.percentages(item.body)) or [
            "none"
        ]
        evidence.append(
            ev.Evidence(
                "claim",
                ev.NUMBER_MISMATCH,
                f"The headline says {', '.join(missing)}, which the story "
                f"never states (its percentages: {', '.join(stated)}).",
                "text",
            )
        )
    moves = signals.price_moves(f"{item.headline}. {item.body}")
    ticker = item.tickers[0] if item.tickers else None
    for move in moves[:2]:
        if ticker is None or move.percent < _MIN_CHECKED_MOVE:
            continue
        try:
            prices = await tools.price_history(ticker, _PRICE_DAYS)
        except tools_lib.ToolError as e:
            evidence.append(
                ev.Evidence(
                    "claim",
                    None,
                    f"Price history of {ticker} is unavailable ({e}).",
                    "prices",
                )
            )
            break
        changes = [
            abs(float(p["change_pct"]))
            for p in prices
            if p.get("change_pct") is not None
        ]
        if not changes:
            continue
        largest = max(changes)
        if largest < move.percent / 2:
            codes.append(ev.NUMBER_MISMATCH)
            evidence.append(
                ev.Evidence(
                    "claim",
                    ev.NUMBER_MISMATCH,
                    f'"{move.text}", but {ticker}\'s largest daily move in '
                    f"the last {_PRICE_DAYS} trading days was {largest:.1f}%.",
                    "prices",
                )
            )
        else:
            evidence.append(
                ev.Evidence(
                    "claim",
                    None,
                    f"{ticker} moved up to {largest:.1f}% a day recently, in "
                    f'line with "{move.text}".',
                    "prices",
                )
            )
    if not evidence:
        evidence.append(
            ev.Evidence(
                "claim",
                None,
                "Every number in the headline is in the story.",
                "text",
            )
        )
    return ev.Finding(tuple(dict.fromkeys(codes)), tuple(evidence))


def style_signals(item: Item) -> ev.Finding:
    """SENSATIONAL_HEADLINE (see module docstring)."""
    hits = signals.sensational(item.headline, item.body)
    if not hits:
        return ev.Finding(
            (),
            (ev.Evidence("style", None, "The headline is sober.", "text"),),
        )
    shown = ", ".join(f'"{h}"' for h in dict.fromkeys(hits))
    return ev.Finding(
        (ev.SENSATIONAL_HEADLINE,),
        (
            ev.Evidence(
                "style",
                ev.SENSATIONAL_HEADLINE,
                f"Sensational headline: {shown}.",
                "text",
            ),
        ),
    )


def fabricated(
    item: Item,
    codes: Sequence[str],
    tier: str,
    found: CorroborationResult,
) -> ev.Finding:
    """FABRICATED_CLAIM: a material event only an untrusted source reports.

    A real company's material event (a deal, an executive leaving, a
    breakup, a halt...) must be filed with the SEC within days, and other
    outlets pick it up. From a low-reputation or unknown source, with no
    filing and no other outlet after both searches ran, it is fabricated.

    Args:
        item: The item.
        codes: The codes found so far.
        tier: The source's reputation tier.
        found: The corroboration check.

    Returns:
        The finding (empty when the rule doesn't apply).
    """
    if {"FAKE_COMPANY", "FAKE_TICKER"} & set(codes):
        return ev.Finding()
    if tier not in _UNTRUSTED_TIERS or not found.searched:
        return ev.Finding()
    if found.primary_source or found.independent_sources:
        return ev.Finding()
    events = signals.material_event(f"{item.headline}. {item.body}")
    if not events:
        return ev.Finding()
    shown = ", ".join(f'"{e}"' for e in dict.fromkeys(events))
    message = (
        f"A material event ({shown}) from a {tier}-reputation source, with "
        "no SEC filing and no other outlet reporting it: a real one would "
        "have both."
    )
    return ev.Finding(
        (ev.FABRICATED_CLAIM, ev.NO_CORROBORATION),
        (ev.Evidence("claim", ev.FABRICATED_CLAIM, message, "rules"),),
    )
