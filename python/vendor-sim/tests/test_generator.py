"""Tests for the synthetic feed generator."""

import collections
import datetime
import hashlib

import pytest

from vendor_sim import companies
from vendor_sim import generator
from vendor_sim import templates

_DAY = datetime.date(2026, 9, 24)


def test_default_mix_has_100_items_with_unique_ids():
    feed = generator.generate_feed(_DAY)
    assert len(feed.items) == 100
    assert len({item.id for item in feed.items}) == 100
    assert [label.id for label in feed.labels] == [
        item.id for item in feed.items
    ]


def test_same_seed_and_date_is_reproducible():
    first = generator.generate_feed(_DAY, seed=42)
    again = generator.generate_feed(_DAY, seed=42)
    other_seed = generator.generate_feed(_DAY, seed=7)

    def as_json(feed):
        return [item.to_json() for item in feed.items]

    assert as_json(first) == as_json(again)
    assert as_json(first) != as_json(other_seed)


def test_label_counts_follow_the_mix():
    labels = generator.generate_feed(_DAY).labels
    kinds = collections.Counter(label.kind for label in labels)
    assert kinds == {"real": 60, "fake": 15, "misleading": 10, "duplicate": 15}


def test_every_duplicate_type_is_present():
    labels = generator.generate_feed(_DAY).labels
    dup_types = {label.dup_type for label in labels if label.dup_type}
    assert dup_types == {"exact", "url", "near", "paraphrase", "stale"}


def test_injection_items_are_fake_and_labeled():
    labels = generator.generate_feed(_DAY).labels
    injected = [
        label for label in labels if "INJECTION_ATTEMPT" in label.reason_codes
    ]
    assert len(injected) == 2
    assert all(label.expected_verdict == "FAKE" for label in injected)


def test_every_item_is_marked_synthetic():
    for item in generator.generate_feed(_DAY).items:
        prefix = templates.HEADLINE_PREFIX.upper()
        assert item.headline.upper().startswith(prefix)
        assert item.body.endswith(templates.FOOTER)
        assert item.synthetic is True
        assert item.source_domain.endswith((".example", ".test"))


def test_fake_companies_are_not_real():
    real = {company.ticker for company in companies.REAL_COMPANIES}
    fake = {company.ticker for company in companies.FAKE_COMPANIES}
    assert not real & fake


def test_stale_duplicates_copy_an_earlier_feed():
    feed = generator.generate_feed(_DAY)
    for label in feed.labels:
        if label.dup_type != "stale":
            continue
        old_day = datetime.date.fromisoformat(
            f"{label.dup_of[4:8]}-{label.dup_of[8:10]}-{label.dup_of[10:12]}"
        )
        assert old_day < _DAY
        old_items = generator.generate_feed(old_day).items
        old = {item.id: item for item in old_items}[label.dup_of]
        copy = {item.id: item for item in feed.items}[label.id]
        assert (copy.headline, copy.body) == (old.headline, old.body)


def _legacy_hash(item: generator.NewsItem) -> str:
    """What the C++11 ingester hashes: lowercase, whitespace collapsed."""
    text = f"{item.headline}\n{item.body}".lower()
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()


@pytest.mark.parametrize(
    "day", [_DAY + datetime.timedelta(days=days) for days in range(0, 30, 3)]
)
def test_only_exact_url_and_stale_copies_share_text(day):
    """Exact-hash dedup (legacy) catches exact, url and stale copies only.

    Every other pair of items, within a day or across the 5-day history,
    must differ in text, so the legacy duplicate count is predictable.
    """
    feed = generator.generate_feed(day)
    labels = {label.id: label for label in feed.labels}
    history = [
        item
        for days_back in range(1, 6)
        for item in generator.generate_feed(
            day - datetime.timedelta(days=days_back)
        ).items
    ]
    seen = {_legacy_hash(item): item.id for item in history}
    caught = []
    for item in feed.items:
        key = _legacy_hash(item)
        if key in seen:
            caught.append((item.id, seen[key]))
        else:
            seen[key] = item.id
    hash_types = ("exact", "url", "stale")
    expected = sum(1 for label in feed.labels if label.dup_type in hash_types)
    assert len(caught) == expected
    for copy_id, first_id in caught:
        pair = {labels.get(copy_id), labels.get(first_id)} - {None}
        assert any(label.dup_type in hash_types for label in pair)


def test_published_at_is_before_the_open():
    for item in generator.generate_feed(_DAY).items:
        # 05:15 ET is 09:15 UTC during daylight saving time.
        published = item.published_at.strftime("%Y-%m-%d %H:%M")
        assert published <= "2026-09-24 09:15"


def test_mix_parse():
    mix = generator.FeedMix.parse(
        "real=10,fake=4,injection=1,misleading=3,duplicates=3"
    )
    assert mix.total == 20
    assert len(generator.generate_feed(_DAY, mix=mix).items) == 20
    with pytest.raises(ValueError):
        generator.FeedMix.parse("fake=1,injection=2")
    with pytest.raises(ValueError):
        generator.FeedMix.parse("bogus=1")
