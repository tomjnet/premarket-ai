import hashlib
from collections import Counter
from datetime import date, timedelta

import pytest

from vendor_sim import companies as co
from vendor_sim import templates as tpl
from vendor_sim.generator import FeedMix, generate_feed

DAY = date(2026, 9, 24)


def test_default_mix_has_100_items_with_unique_ids():
    feed = generate_feed(DAY)
    assert len(feed.items) == 100
    assert len({item.id for item in feed.items}) == 100
    assert [label.id for label in feed.labels] == [item.id for item in feed.items]


def test_same_seed_and_date_is_reproducible():
    a = generate_feed(DAY, seed=42)
    b = generate_feed(DAY, seed=42)
    assert [i.to_json() for i in a.items] == [i.to_json() for i in b.items]
    c = generate_feed(DAY, seed=7)
    assert [i.to_json() for i in a.items] != [i.to_json() for i in c.items]


def test_label_counts_follow_the_mix():
    kinds = Counter(label.kind for label in generate_feed(DAY).labels)
    assert kinds == {"real": 60, "fake": 15, "misleading": 10, "duplicate": 15}


def test_every_duplicate_type_is_present():
    dup_types = Counter(label.dup_type for label in generate_feed(DAY).labels if label.dup_type)
    assert set(dup_types) == {"exact", "url", "near", "paraphrase", "stale"}


def test_injection_items_are_fake_and_labeled():
    labels = generate_feed(DAY).labels
    injected = [lb for lb in labels if "INJECTION_ATTEMPT" in lb.reason_codes]
    assert len(injected) == 2
    assert all(lb.expected_verdict == "FAKE" for lb in injected)


def test_every_item_is_marked_synthetic():
    for item in generate_feed(DAY).items:
        assert item.headline.upper().startswith(tpl.HEADLINE_PREFIX.upper())
        assert item.body.endswith(tpl.FOOTER)
        assert item.synthetic is True
        assert item.source_domain.endswith((".example", ".test"))


def test_fake_companies_are_not_real():
    real = {c.ticker for c in co.REAL_COMPANIES}
    assert not real & {c.ticker for c in co.FAKE_COMPANIES}


def test_stale_duplicates_copy_an_earlier_feed():
    feed = generate_feed(DAY)
    for label in feed.labels:
        if label.dup_type != "stale":
            continue
        old_day = date.fromisoformat(
            f"{label.dup_of[4:8]}-{label.dup_of[8:10]}-{label.dup_of[10:12]}"
        )
        assert old_day < DAY
        old = {i.id: i for i in generate_feed(old_day).items}[label.dup_of]
        copy = {i.id: i for i in feed.items}[label.id]
        assert (copy.headline, copy.body) == (old.headline, old.body)


def _legacy_hash(item) -> str:
    """What the C++11 ingester hashes: lowercase, whitespace collapsed."""
    text = f"{item.headline}\n{item.body}".lower()
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()


@pytest.mark.parametrize("day", [DAY + timedelta(days=d) for d in range(0, 30, 3)])
def test_only_exact_url_and_stale_copies_share_text(day):
    """Exact-hash dedup (legacy) catches exact, url and stale copies only.

    Every other pair of items, within a day or across the 5-day history,
    must differ in text, so the legacy duplicate count is predictable.
    """
    feed = generate_feed(day)
    labels = {label.id: label for label in feed.labels}
    history = [i for k in range(1, 6) for i in generate_feed(day - timedelta(days=k)).items]
    seen = {_legacy_hash(item): item.id for item in history}
    caught = []
    for item in feed.items:
        key = _legacy_hash(item)
        if key in seen:
            caught.append((item.id, seen[key]))
        else:
            seen[key] = item.id
    expected = sum(1 for lb in feed.labels if lb.dup_type in ("exact", "url", "stale"))
    assert len(caught) == expected
    for a, b in caught:
        pair = {labels.get(a), labels.get(b)} - {None}
        assert any(lb.dup_type in ("exact", "url", "stale") for lb in pair)


def test_published_at_is_before_the_open():
    for item in generate_feed(DAY).items:
        # 05:15 ET is 09:15 UTC during daylight saving time.
        assert item.published_at.strftime("%Y-%m-%d %H:%M") <= "2026-09-24 09:15"


def test_mix_parse():
    mix = FeedMix.parse("real=10,fake=4,injection=1,misleading=3,duplicates=3")
    assert mix.total == 20
    assert len(generate_feed(DAY, mix=mix).items) == 20
    with pytest.raises(ValueError):
        FeedMix.parse("fake=1,injection=2")
    with pytest.raises(ValueError):
        FeedMix.parse("bogus=1")
