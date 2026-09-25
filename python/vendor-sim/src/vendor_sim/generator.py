"""Deterministic synthetic vendor feed.

The same (seed, date) always gives the same 100 items and labels. Duplicates
point at the item they copy (``dup_of``); stale duplicates copy a real item
from an earlier day's feed, so the legacy 7-day hash lookup can catch them.

Typical usage:

    feed = generator.generate_feed(datetime.date(2026, 9, 24), seed=42)
    for item, label in zip(feed.items, feed.labels, strict=True):
        ...
"""

from __future__ import annotations

import dataclasses
import datetime
import itertools
import random
import re
from typing import Any
import zoneinfo

from vendor_sim import companies
from vendor_sim import templates

_NEW_YORK = zoneinfo.ZoneInfo("America/New_York")
_DUP_TYPES = ("exact", "url", "near", "paraphrase", "stale")
_FAKE_KINDS = ("fake_company", "fabricated", "spoofed", "fake_ticker")
_MISLEADING_KINDS = ("number_mismatch", "sensational", "old_news")


@dataclasses.dataclass(frozen=True)
class FeedMix:
    """How many items of each kind one day's feed has.

    Attributes:
        real: Real stories about real companies.
        fake: FAKE stories: invented company or ticker, fabricated claim, or
            spoofed source.
        injection: FAKE stories that also carry prompt-injection text. A
            subset of ``fake``.
        misleading: MISLEADING stories: wrong number, sensational headline or
            old news.
        duplicates: Copies of other stories: exact, url, near, paraphrase and
            stale.
    """

    real: int = 60
    fake: int = 15
    injection: int = 2
    misleading: int = 10
    duplicates: int = 15

    @property
    def total(self) -> int:
        """The number of items in the feed."""
        return self.real + self.fake + self.misleading + self.duplicates

    @classmethod
    def parse(cls, text: str) -> FeedMix:
        """Parses a mix such as ``"real=60,fake=15,injection=2"``.

        Args:
            text: Comma-separated ``key=count`` pairs. Missing keys keep their
                defaults, so an empty string gives the default mix.

        Returns:
            The parsed mix.

        Raises:
            ValueError: A key is unknown, a count is not an integer or is
                negative, or ``injection`` is larger than ``fake``.
        """
        names = {f.name for f in dataclasses.fields(cls)}
        values: dict[str, int] = {}
        parts = (part.strip() for part in text.split(","))
        for part in filter(None, parts):
            key, _, value = part.partition("=")
            if key not in names:
                raise ValueError(f"unknown mix key: {key!r}")
            values[key] = int(value)
        mix = cls(**values)
        if mix.injection > mix.fake:
            raise ValueError("injection must be <= fake")
        if min(dataclasses.astuple(mix)) < 0:
            raise ValueError("mix values must be >= 0")
        return mix


@dataclasses.dataclass(frozen=True)
class NewsItem:
    """One news item as the vendor sends it.

    Attributes:
        id: The vendor's item ID, ``VND-<yyyymmdd>-<nnn>``.
        headline: The headline, starting with ``[SYNTHETIC]``.
        body: Dateline, story and the synthetic-data footer.
        source_url: Where the story claims to come from.
        source_domain: The host part of ``source_url``.
        published_at: The publication time (timezone-aware).
        tickers: The tickers the story is about.
        synthetic: Always True: every item is generated.
    """

    id: str
    headline: str
    body: str
    source_url: str
    source_domain: str
    published_at: datetime.datetime
    tickers: tuple[str, ...]
    synthetic: bool = True

    def to_json(self) -> dict[str, Any]:
        """Returns the item as the feed API serves it."""
        published = self.published_at.astimezone(datetime.UTC)
        return {
            "id": self.id,
            "headline": self.headline,
            "body": self.body,
            "source_url": self.source_url,
            "source_domain": self.source_domain,
            "published_at": published.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tickers": list(self.tickers),
            "synthetic": self.synthetic,
        }


@dataclasses.dataclass(frozen=True)
class Label:
    """Ground truth for one item. Never served by the feed API.

    Attributes:
        id: The ID of the item this label describes.
        kind: ``real``, ``fake``, ``misleading`` or ``duplicate``.
        subtype: The template or trick used, for example ``earnings`` or
            ``spoofed``.
        expected_verdict: ``VERIFIED``, ``UNVERIFIED``, ``MISLEADING`` or
            ``FAKE``.
        reason_codes: The reason codes a correct verdict carries.
        dup_of: For a duplicate, the ID of the item it copies.
        dup_type: For a duplicate, ``exact``, ``url``, ``near``,
            ``paraphrase`` or ``stale``.
    """

    id: str
    kind: str
    subtype: str
    expected_verdict: str
    reason_codes: tuple[str, ...] = ()
    dup_of: str | None = None
    dup_type: str | None = None

    def to_json(self) -> dict[str, Any]:
        """Returns the label as one line of ``labels.jsonl``."""
        data = dataclasses.asdict(self)
        data["reason_codes"] = list(self.reason_codes)
        return data


@dataclasses.dataclass
class Feed:
    """One day's feed.

    Attributes:
        feed_date: The day the feed is for.
        items: The items, in the order the vendor sends them.
        labels: The ground truth; ``labels[i]`` describes ``items[i]``.
    """

    feed_date: datetime.date
    items: list[NewsItem] = dataclasses.field(default_factory=list)
    labels: list[Label] = dataclasses.field(default_factory=list)


# Paraphrase inputs are kept per original, so a paraphrase can reuse the facts.
_Facts = dict[str, tuple[templates.Template, dict[str, Any]]]


def _item_id(day: datetime.date, number: int) -> str:
    return f"VND-{day:%Y%m%d}-{number:03d}"


def _slug(text: str) -> str:
    text = text.removeprefix(templates.HEADLINE_PREFIX).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:60]


def _published_at(day: datetime.date, rng: random.Random) -> datetime.datetime:
    """A time between 16:00 ET the day before and 05:15 ET on ``day``."""
    start = datetime.datetime.combine(
        day - datetime.timedelta(days=1), datetime.time(16, 0), _NEW_YORK
    )
    offset = rng.randint(0, 13 * 60 + 15)
    return (start + datetime.timedelta(minutes=offset)).astimezone(datetime.UTC)


def _params(
    rng: random.Random,
    company: companies.Company,
    other: companies.Company,
) -> dict[str, Any]:
    """Random facts that fill a template's placeholders."""
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
        "person": rng.choice(templates.PEOPLE),
        "area": rng.choice(templates.AREAS),
        "system": rng.choice(templates.SYSTEMS),
        "parts": rng.choice(("two", "three", "four")),
        "weeks": rng.randint(2, 12),
        "meeting": f"{rng.choice(templates.MONTHS)} {rng.randint(1, 28)}",
    }


def _body(day: datetime.date, text: str) -> str:
    """Dateline + story + synthetic footer, as the vendor formats every item."""
    dateline = f"NEW YORK, {day:%B} {day.day} (Acme Market Wire) --"
    return f"{dateline} {text}\n\n{templates.FOOTER}"


def _make_item(
    day: datetime.date,
    number: int,
    rng: random.Random,
    headline: str,
    body: str,
    domain: str,
    tickers: tuple[str, ...],
) -> NewsItem:
    """Builds item ``number`` of ``day`` with a random publication time."""
    headline = templates.HEADLINE_PREFIX + headline
    slug = _slug(headline)
    return NewsItem(
        id=_item_id(day, number),
        headline=headline,
        body=_body(day, body),
        source_url=f"https://{domain}/{day:%Y/%m/%d}/{slug}-{number:03d}",
        source_domain=domain,
        published_at=_published_at(day, rng),
        tickers=tickers,
    )


def _pick_two(
    rng: random.Random, pool: tuple[companies.Company, ...]
) -> tuple[companies.Company, companies.Company]:
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


@dataclasses.dataclass
class _Originals:
    """One day's original items while they are generated.

    Attributes:
        day: The feed date.
        rng: The random source shared by every original of the day.
        items: The items kept so far; item N has ID number N.
        labels: The labels of ``items``, in the same order.
        facts: The template and facts behind each real item.
        used: The text keys of ``items``, so no two items share text.
    """

    day: datetime.date
    rng: random.Random
    items: list[NewsItem] = dataclasses.field(default_factory=list)
    labels: list[Label] = dataclasses.field(default_factory=list)
    facts: _Facts = dataclasses.field(default_factory=dict)
    used: set[str] = dataclasses.field(default_factory=set)

    def new_item(
        self, headline: str, body: str, domain: str, tickers: tuple[str, ...]
    ) -> NewsItem:
        """Builds the next item. It is kept only if ``keep`` accepts it."""
        return _make_item(
            self.day,
            len(self.items) + 1,
            self.rng,
            headline,
            body,
            domain,
            tickers,
        )

    def keep(self, item: NewsItem, label: Label) -> bool:
        """Keeps ``item`` unless an earlier item has the same text."""
        if not _claim(self.used, item):
            return False
        self.items.append(item)
        self.labels.append(label)
        return True


def _add_real(originals: _Originals, count: int) -> None:
    """Adds ``count`` real stories about real companies."""
    rng = originals.rng
    added = 0
    while added < count:
        company, other = _pick_two(rng, companies.REAL_COMPANIES)
        template = rng.choice(templates.REAL_TEMPLATES)
        params = _params(rng, company, other)
        tickers = (company.ticker,)
        if template.kind == "partnership":
            tickers = (company.ticker, other.ticker)
        item = originals.new_item(
            template.headlines[0].format(**params),
            template.bodies[0].format(**params),
            rng.choice(companies.TRUSTED_DOMAINS),
            tickers,
        )
        label = Label(item.id, "real", template.kind, "VERIFIED")
        if originals.keep(item, label):
            originals.facts[item.id] = (template, params)
            added += 1


def _fake_story(
    rng: random.Random, kind: str
) -> tuple[str, str, str, tuple[str, ...], tuple[str, ...]]:
    """Writes one FAKE story of ``kind``.

    Args:
        rng: The day's random source.
        kind: One of ``_FAKE_KINDS``.

    Returns:
        The headline, body, source domain, tickers and reason codes.
    """
    real, other = _pick_two(rng, companies.REAL_COMPANIES)
    fake = rng.choice(companies.FAKE_COMPANIES)
    if kind == "fake_company":
        params = _params(rng, fake, real)
        headline, body = rng.choice(templates.FAKE_COMPANY_TEMPLATES)
        domain = rng.choice(companies.LOW_QUALITY_DOMAINS)
        tickers = (fake.ticker,)
        reasons = ("FAKE_COMPANY", "FAKE_TICKER")
    elif kind == "fake_ticker":
        # A real company name with a ticker that doesn't exist ("QZ" suffix).
        bogus = companies.Company(
            real.ticker + "QZ", real.name, real.short, real.sector
        )
        params = _params(rng, bogus, other)
        earnings = templates.REAL_TEMPLATES[0]
        headline, body = earnings.headlines[0], earnings.bodies[0]
        domain = rng.choice(companies.LOW_QUALITY_DOMAINS)
        tickers = (bogus.ticker,)
        reasons = ("FAKE_TICKER",)
    elif kind == "spoofed":
        params = _params(rng, real, other)
        headline, body = rng.choice(templates.FABRICATED_TEMPLATES)
        domain = rng.choice(companies.SPOOFED_DOMAINS)
        tickers = (real.ticker,)
        reasons = ("SPOOFED_SOURCE", "FABRICATED_CLAIM")
    else:  # fabricated
        params = _params(rng, real, other)
        headline, body = rng.choice(templates.FABRICATED_TEMPLATES)
        domain = rng.choice(companies.LOW_QUALITY_DOMAINS)
        tickers = (real.ticker,)
        reasons = ("FABRICATED_CLAIM", "NO_CORROBORATION")
    return (
        headline.format(**params),
        body.format(**params),
        domain,
        tickers,
        reasons,
    )


def _add_fake(originals: _Originals, count: int, injection: int) -> None:
    """Adds ``count`` FAKE stories; the first ``injection`` carry injections."""
    fake_kinds = itertools.cycle(_FAKE_KINDS)
    kind = next(fake_kinds)
    added = 0
    while added < count:
        headline, body, domain, tickers, reasons = _fake_story(
            originals.rng, kind
        )
        if added < injection:
            lines = templates.INJECTION_LINES
            body = f"{body} {lines[added % len(lines)]}"
            reasons = (*reasons, "INJECTION_ATTEMPT")
        item = originals.new_item(headline, body, domain, tickers)
        label = Label(item.id, "fake", kind, "FAKE", reasons)
        if originals.keep(item, label):
            added += 1
            kind = next(fake_kinds)


def _add_misleading(originals: _Originals, count: int) -> None:
    """Adds ``count`` MISLEADING stories about real companies."""
    rng = originals.rng
    misleading_kinds = itertools.cycle(_MISLEADING_KINDS)
    kind = next(misleading_kinds)
    added = 0
    while added < count:
        company, other = _pick_two(rng, companies.REAL_COMPANIES)
        params = _params(rng, company, other)
        reasons: tuple[str, ...]
        if kind == "number_mismatch":
            headline, body = templates.NUMBER_MISMATCH
            reasons = ("NUMBER_MISMATCH", "SENSATIONAL_HEADLINE")
        elif kind == "sensational":
            headline, body = templates.SENSATIONAL
            reasons = ("SENSATIONAL_HEADLINE",)
        else:  # old_news
            days_ago = rng.randint(60, 300)
            old = originals.day - datetime.timedelta(days=days_ago)
            params["old_date"] = f"{old:%B} {old.day}, {old.year}"
            headline, body = templates.OLD_NEWS
            reasons = ("STALE",)
        item = originals.new_item(
            headline.format(**params),
            body.format(**params),
            rng.choice(companies.TRUSTED_DOMAINS),
            (company.ticker,),
        )
        label = Label(item.id, "misleading", kind, "MISLEADING", reasons)
        if originals.keep(item, label):
            added += 1
            kind = next(misleading_kinds)


def _originals(day: datetime.date, seed: int, mix: FeedMix) -> _Originals:
    """Real, FAKE and MISLEADING items for ``day`` (IDs 1..N, no copies)."""
    rng = random.Random(f"{seed}:{day.isoformat()}:originals")
    originals = _Originals(day, rng)
    _add_real(originals, mix.real)
    _add_fake(originals, mix.fake, mix.injection)
    _add_misleading(originals, mix.misleading)
    return originals


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
    number: int,
    day: datetime.date,
    published: datetime.datetime,
    facts: _Facts,
    rng: random.Random,
) -> NewsItem:
    """One duplicate of ``source`` (exact, url, near or paraphrase)."""
    if dup_type == "exact":
        # Same text after case and whitespace normalization.
        body = source.body.replace(" ", "  ", 3).replace("\n\n", "\n \n", 1)
        return dataclasses.replace(
            source, id=new_id, headline=source.headline.upper(), body=body
        )
    if dup_type == "url":
        tracking = "?utm_source=vendorfeed&utm_medium=api"
        return dataclasses.replace(
            source, id=new_id, source_url=source.source_url + tracking
        )
    if dup_type == "near":
        headline, body = _near_copy(source, rng)
        return dataclasses.replace(
            source,
            id=new_id,
            headline=headline,
            body=body,
            published_at=published,
        )
    template, params = facts[source.id]  # paraphrase
    headline = template.headlines[1].format(**params)
    domain = rng.choice(companies.TRUSTED_DOMAINS)
    slug = _slug(headline)
    return dataclasses.replace(
        source,
        id=new_id,
        headline=templates.HEADLINE_PREFIX + headline,
        body=_body(day, template.bodies[1].format(**params)),
        source_domain=domain,
        source_url=f"https://{domain}/{day:%Y/%m/%d}/{slug}-{number:03d}",
        published_at=published,
    )


def _stale_copy(
    day: datetime.date,
    seed: int,
    mix: FeedMix,
    new_id: str,
    published: datetime.datetime,
    rng: random.Random,
) -> tuple[NewsItem, Label] | None:
    """Re-sends a real item from 1 to 5 days earlier as news of ``day``.

    Returns:
        The copy and its label, or None if that day's feed has no real items.
    """
    old_day = day - datetime.timedelta(days=rng.randint(1, 5))
    old = _originals(old_day, seed, mix)
    pairs = zip(old.items, old.labels, strict=True)
    old_real = [item for item, label in pairs if label.kind == "real"]
    if not old_real:
        return None
    source = rng.choice(old_real)
    duplicate = dataclasses.replace(source, id=new_id, published_at=published)
    label = Label(
        new_id,
        "duplicate",
        "stale",
        "MISLEADING",
        ("STALE",),
        source.id,
        "stale",
    )
    return duplicate, label


def _duplicates(
    day: datetime.date, seed: int, mix: FeedMix, originals: _Originals
) -> list[tuple[NewsItem, Label]]:
    """The day's duplicates, cycling through every duplicate type."""
    rng = random.Random(f"{seed}:{day.isoformat()}:duplicates")
    label_by_id = {label.id: label for label in originals.labels}
    real_ids = [label.id for label in originals.labels if label.kind == "real"]
    copyable = [
        item
        for item in originals.items
        if "INJECTION_ATTEMPT" not in label_by_id[item.id].reason_codes
    ]
    by_id = {item.id: item for item in originals.items}
    used = {_text_key(item) for item in originals.items}

    duplicates: list[tuple[NewsItem, Label]] = []
    number = len(originals.items)
    dup_types = itertools.cycle(_DUP_TYPES)
    for _ in range(mix.duplicates):
        if not copyable:
            break
        number += 1
        dup_type = next(dup_types)
        if dup_type == "paraphrase" and not real_ids:
            dup_type = "exact"
        new_id = _item_id(day, number)
        published = _published_at(day, rng)
        if dup_type == "stale":
            stale = _stale_copy(day, seed, mix, new_id, published, rng)
            if stale is None:
                number -= 1
                continue
            duplicates.append(stale)
            continue
        for _attempt in range(50):
            if dup_type == "paraphrase":
                source = by_id[rng.choice(real_ids)]
            else:
                source = rng.choice(copyable)
            duplicate = _copy(
                dup_type,
                source,
                new_id,
                number,
                day,
                published,
                originals.facts,
                rng,
            )
            # exact/url copies share text on purpose; the others must not.
            if dup_type in ("exact", "url") or _claim(used, duplicate):
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
        duplicates.append((duplicate, label))
    return duplicates


def generate_feed(
    day: datetime.date, seed: int = 42, mix: FeedMix | None = None
) -> Feed:
    """Builds one day's feed: originals and duplicates, shuffled.

    Args:
        day: The feed date.
        seed: The random seed. The same seed and day give the same feed.
        mix: How many items of each kind. None means ``FeedMix()``.

    Returns:
        The feed, with ``labels[i]`` describing ``items[i]``.
    """
    if mix is None:
        mix = FeedMix()
    originals = _originals(day, seed, mix)
    paired = list(zip(originals.items, originals.labels, strict=True))
    paired += _duplicates(day, seed, mix, originals)
    random.Random(f"{seed}:{day.isoformat()}:order").shuffle(paired)
    return Feed(
        feed_date=day,
        items=[item for item, _ in paired],
        labels=[label for _, label in paired],
    )


def today_new_york() -> datetime.date:
    """Returns today's date in New York, the market's time zone."""
    return datetime.datetime.now(_NEW_YORK).date()
