"""Deterministic synthetic vendor feed.

The same (seed, date) always gives the same 100 items and labels. Duplicates
point at the item they copy (``dup_of``); stale duplicates copy a real item
from an earlier day's feed, so the legacy 7-day hash lookup can catch them.
"""

from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from itertools import cycle
from zoneinfo import ZoneInfo

from vendor_sim import companies as co
from vendor_sim import templates as tpl

NEW_YORK = ZoneInfo("America/New_York")
DUP_TYPES = ("exact", "url", "near", "paraphrase", "stale")
FAKE_KINDS = ("fake_company", "fabricated", "spoofed", "fake_ticker")
MISLEADING_KINDS = ("number_mismatch", "sensational", "old_news")


@dataclass(frozen=True)
class FeedMix:
    """How many items of each kind one day's feed has."""

    real: int = 60
    fake: int = 15
    injection: int = 2  # a subset of ``fake``
    misleading: int = 10
    duplicates: int = 15

    @property
    def total(self) -> int:
        return self.real + self.fake + self.misleading + self.duplicates

    @classmethod
    def parse(cls, text: str) -> FeedMix:
        """Parses ``"real=60,fake=15,injection=2,misleading=10,duplicates=15"``."""
        values: dict[str, int] = {}
        for part in filter(None, (p.strip() for p in text.split(","))):
            key, _, value = part.partition("=")
            if key not in cls.__dataclass_fields__:
                raise ValueError(f"unknown mix key: {key!r}")
            values[key] = int(value)
        mix = cls(**values)
        if mix.injection > mix.fake:
            raise ValueError("injection must be <= fake")
        if min(asdict(mix).values()) < 0:
            raise ValueError("mix values must be >= 0")
        return mix


@dataclass(frozen=True)
class NewsItem:
    id: str
    headline: str
    body: str
    source_url: str
    source_domain: str
    published_at: datetime
    tickers: tuple[str, ...]
    synthetic: bool = True

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "headline": self.headline,
            "body": self.body,
            "source_url": self.source_url,
            "source_domain": self.source_domain,
            "published_at": self.published_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tickers": list(self.tickers),
            "synthetic": self.synthetic,
        }


@dataclass(frozen=True)
class Label:
    """Ground truth for one item. Never served by the feed API."""

    id: str
    kind: str  # real | fake | misleading | duplicate
    subtype: str
    expected_verdict: str  # VERIFIED | UNVERIFIED | MISLEADING | FAKE
    reason_codes: tuple[str, ...] = ()
    dup_of: str | None = None
    dup_type: str | None = None

    def to_json(self) -> dict:
        data = asdict(self)
        data["reason_codes"] = list(self.reason_codes)
        return data


@dataclass
class Feed:
    feed_date: date
    items: list[NewsItem] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)


def _item_id(day: date, n: int) -> str:
    return f"VND-{day:%Y%m%d}-{n:03d}"


def _slug(text: str) -> str:
    text = text.removeprefix(tpl.HEADLINE_PREFIX).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:60]


def _published_at(day: date, rng: random.Random) -> datetime:
    """A time between 16:00 ET the day before and 05:15 ET on ``day``."""
    start = datetime.combine(day - timedelta(days=1), time(16, 0), NEW_YORK)
    offset = rng.randint(0, 13 * 60 + 15)
    return (start + timedelta(minutes=offset)).astimezone(UTC)


def _params(rng: random.Random, company: co.Company, other: co.Company) -> dict:
    pct = rng.randint(3, 24)
    return {
        "name": company.name,
        "short": company.short,
        "ticker": company.ticker,
        "other_name": other.name,
        "other_short": other.short,
        "other_ticker": other.ticker,
        "quarter": rng.randint(1, 4),
        "revenue": f"{rng.uniform(5, 120):.1f}",
        "eps": f"{rng.uniform(0.4, 9.5):.2f}",
        "pct": pct,
        "big_pct": pct * 10,
        "dividend": f"{rng.uniform(0.2, 3.5):.2f}",
        "buyback": f"{rng.uniform(1, 90):.1f}",
        "deal": rng.randint(2, 40),
        "person": rng.choice(tpl.PEOPLE),
        "area": rng.choice(tpl.AREAS),
        "system": rng.choice(tpl.SYSTEMS),
        "parts": rng.choice(("two", "three", "four")),
        "weeks": rng.randint(2, 12),
        "meeting": f"{rng.choice(tpl.MONTHS)} {rng.randint(1, 28)}",
    }


def _body(day: date, text: str) -> str:
    """Dateline + story + synthetic footer, as the vendor formats every item."""
    return f"NEW YORK, {day:%B} {day.day} (Acme Market Wire) -- {text}\n\n{tpl.FOOTER}"


def _make_item(
    day: date,
    n: int,
    rng: random.Random,
    headline: str,
    body: str,
    domain: str,
    tickers: tuple[str, ...],
) -> NewsItem:
    headline = tpl.HEADLINE_PREFIX + headline
    return NewsItem(
        id=_item_id(day, n),
        headline=headline,
        body=_body(day, body),
        source_url=f"https://{domain}/{day:%Y/%m/%d}/{_slug(headline)}-{n:03d}",
        source_domain=domain,
        published_at=_published_at(day, rng),
        tickers=tickers,
    )


def _pick_two(rng: random.Random, pool: tuple[co.Company, ...]):
    first, second = rng.sample(pool, 2)
    return first, second


def _text_key(item: NewsItem) -> str:
    """The text as exact-hash dedup sees it: lowercase, whitespace collapsed."""
    return " ".join(f"{item.headline}\n{item.body}".lower().split())


def _claim(used: set[str], item: NewsItem) -> bool:
    """Records ``item``'s text; False if an earlier item already has it."""
    key = _text_key(item)
    if key in used:
        return False
    used.add(key)
    return True


# Paraphrase inputs are kept per original, so a paraphrase can reuse the facts.
_Facts = dict[str, tuple[tpl.Template, dict]]


def _originals(day: date, seed: int, mix: FeedMix) -> tuple[list[NewsItem], list[Label], _Facts]:
    """Real, FAKE and MISLEADING items for ``day`` (ids 1..N, no duplicates)."""
    rng = random.Random(f"{seed}:{day.isoformat()}:originals")
    items: list[NewsItem] = []
    labels: list[Label] = []
    facts: _Facts = {}
    used: set[str] = set()
    n = 0

    while n < mix.real:
        company, other = _pick_two(rng, co.REAL_COMPANIES)
        template = rng.choice(tpl.REAL_TEMPLATES)
        params = _params(rng, company, other)
        tickers = (company.ticker,)
        if template.kind == "partnership":
            tickers = (company.ticker, other.ticker)
        item = _make_item(
            day,
            n + 1,
            rng,
            template.headlines[0].format(**params),
            template.bodies[0].format(**params),
            rng.choice(co.TRUSTED_DOMAINS),
            tickers,
        )
        if not _claim(used, item):
            continue
        n += 1
        items.append(item)
        labels.append(Label(item.id, "real", template.kind, "VERIFIED"))
        facts[item.id] = (template, params)

    fake_kinds = cycle(FAKE_KINDS)
    i = 0
    kind = next(fake_kinds)
    while i < mix.fake:
        real, other = _pick_two(rng, co.REAL_COMPANIES)
        fake = rng.choice(co.FAKE_COMPANIES)
        if kind == "fake_company":
            params = _params(rng, fake, real)
            headline, body = rng.choice(tpl.FAKE_COMPANY_TEMPLATES)
            domain = rng.choice(co.LOW_QUALITY_DOMAINS)
            tickers = (fake.ticker,)
            reasons = ("FAKE_COMPANY", "FAKE_TICKER")
        elif kind == "fake_ticker":
            # A real company name with a ticker that doesn't exist ("QZ" suffix).
            bogus = co.Company(real.ticker + "QZ", real.name, real.short, real.sector)
            params = _params(rng, bogus, other)
            earnings = tpl.REAL_TEMPLATES[0]
            headline, body = earnings.headlines[0], earnings.bodies[0]
            domain = rng.choice(co.LOW_QUALITY_DOMAINS)
            tickers = (bogus.ticker,)
            reasons = ("FAKE_TICKER",)
        elif kind == "spoofed":
            params = _params(rng, real, other)
            headline, body = rng.choice(tpl.FABRICATED_TEMPLATES)
            domain = rng.choice(co.SPOOFED_DOMAINS)
            tickers = (real.ticker,)
            reasons = ("SPOOFED_SOURCE", "FABRICATED_CLAIM")
        else:  # fabricated
            params = _params(rng, real, other)
            headline, body = rng.choice(tpl.FABRICATED_TEMPLATES)
            domain = rng.choice(co.LOW_QUALITY_DOMAINS)
            tickers = (real.ticker,)
            reasons = ("FABRICATED_CLAIM", "NO_CORROBORATION")
        body = body.format(**params)
        if i < mix.injection:
            body = f"{body} {tpl.INJECTION_LINES[i % len(tpl.INJECTION_LINES)]}"
            reasons = (*reasons, "INJECTION_ATTEMPT")
        item = _make_item(day, n + 1, rng, headline.format(**params), body, domain, tickers)
        if not _claim(used, item):
            continue
        n += 1
        i += 1
        items.append(item)
        labels.append(Label(item.id, "fake", kind, "FAKE", reasons))
        kind = next(fake_kinds)

    misleading_kinds = cycle(MISLEADING_KINDS)
    made = 0
    kind = next(misleading_kinds)
    while made < mix.misleading:
        company, other = _pick_two(rng, co.REAL_COMPANIES)
        params = _params(rng, company, other)
        if kind == "number_mismatch":
            headline, body = tpl.NUMBER_MISMATCH
            reasons: tuple[str, ...] = ("NUMBER_MISMATCH", "SENSATIONAL_HEADLINE")
        elif kind == "sensational":
            headline, body = tpl.SENSATIONAL
            reasons = ("SENSATIONAL_HEADLINE",)
        else:
            old = day - timedelta(days=rng.randint(60, 300))
            params["old_date"] = f"{old:%B} {old.day}, {old.year}"
            headline, body = tpl.OLD_NEWS
            reasons = ("STALE",)
        item = _make_item(
            day,
            n + 1,
            rng,
            headline.format(**params),
            body.format(**params),
            rng.choice(co.TRUSTED_DOMAINS),
            (company.ticker,),
        )
        if not _claim(used, item):
            continue
        n += 1
        made += 1
        items.append(item)
        labels.append(Label(item.id, "misleading", kind, "MISLEADING", reasons))
        kind = next(misleading_kinds)

    return items, labels, facts


def _near_copy(item: NewsItem, rng: random.Random) -> tuple[str, str]:
    """Changes one word of the story: a near-duplicate."""
    swaps = (
        (" said ", " stated "),
        (" rose ", " increased "),
        (" company ", " firm "),
        (" billion", " bln"),
        (" up ", " higher by "),
    )
    story, sep, footer = item.body.partition("\n\n")
    for old, new in rng.sample(swaps, len(swaps)):
        if old in story:
            story = story.replace(old, new, 1)
            break
    else:
        story = story.replace(" -- ", " -- UPDATED: ", 1)
    return item.headline, story + sep + footer


def _copy(
    dup_type: str,
    source: NewsItem,
    new_id: str,
    n: int,
    day: date,
    published: datetime,
    facts: _Facts,
    rng: random.Random,
) -> NewsItem:
    """One duplicate of ``source`` (exact, url, near or paraphrase)."""
    if dup_type == "exact":
        # Same text after case and whitespace normalization.
        body = source.body.replace(" ", "  ", 3).replace("\n\n", "\n \n", 1)
        return replace(source, id=new_id, headline=source.headline.upper(), body=body)
    if dup_type == "url":
        return replace(
            source,
            id=new_id,
            source_url=f"{source.source_url}?utm_source=vendorfeed&utm_medium=api",
        )
    if dup_type == "near":
        headline, body = _near_copy(source, rng)
        return replace(source, id=new_id, headline=headline, body=body, published_at=published)
    template, params = facts[source.id]  # paraphrase
    headline = template.headlines[1].format(**params)
    domain = rng.choice(co.TRUSTED_DOMAINS)
    return replace(
        source,
        id=new_id,
        headline=tpl.HEADLINE_PREFIX + headline,
        body=_body(day, template.bodies[1].format(**params)),
        source_domain=domain,
        source_url=f"https://{domain}/{day:%Y/%m/%d}/{_slug(headline)}-{n:03d}",
        published_at=published,
    )


def generate_feed(day: date, seed: int = 42, mix: FeedMix | None = None) -> Feed:
    """Builds the full feed (originals + duplicates, shuffled) for ``day``."""
    mix = mix or FeedMix()
    items, labels, facts = _originals(day, seed, mix)
    label_by_id = {label.id: label for label in labels}
    rng = random.Random(f"{seed}:{day.isoformat()}:duplicates")
    real_ids = [label.id for label in labels if label.kind == "real"]
    copyable = [
        item for item in items if "INJECTION_ATTEMPT" not in label_by_id[item.id].reason_codes
    ]
    by_id = {item.id: item for item in items}
    used = {_text_key(item) for item in items}

    n = len(items)
    dup_types = cycle(DUP_TYPES)
    for _ in range(mix.duplicates):
        if not copyable:
            break
        n += 1
        dup_type = next(dup_types)
        if dup_type == "paraphrase" and not real_ids:
            dup_type = "exact"
        new_id = _item_id(day, n)
        published = _published_at(day, rng)
        if dup_type == "stale":
            old_day = day - timedelta(days=rng.randint(1, 5))
            old_items, old_labels, _ = _originals(old_day, seed, mix)
            pairs = zip(old_items, old_labels, strict=True)
            old_real = [it for it, lb in pairs if lb.kind == "real"]
            if not old_real:
                n -= 1
                continue
            source = rng.choice(old_real)
            copy = replace(source, id=new_id, published_at=published)
            label = Label(
                new_id, "duplicate", "stale", "MISLEADING", ("STALE",), source.id, "stale"
            )
        else:
            for _attempt in range(50):
                if dup_type == "paraphrase":
                    source = by_id[rng.choice(real_ids)]
                else:
                    source = rng.choice(copyable)
                copy = _copy(dup_type, source, new_id, n, day, published, facts, rng)
                # exact/url copies share text on purpose; the others must not.
                if dup_type in ("exact", "url") or _claim(used, copy):
                    break
            canonical = label_by_id[source.id]
            label = Label(
                new_id,
                "duplicate",
                dup_type,
                canonical.expected_verdict,
                canonical.reason_codes,
                source.id,
                dup_type,
            )
        items.append(copy)
        labels.append(label)

    order = random.Random(f"{seed}:{day.isoformat()}:order")
    paired = list(zip(items, labels, strict=True))
    order.shuffle(paired)
    return Feed(
        feed_date=day,
        items=[item for item, _ in paired],
        labels=[label for _, label in paired],
    )


def today_new_york() -> date:
    return datetime.now(NEW_YORK).date()
