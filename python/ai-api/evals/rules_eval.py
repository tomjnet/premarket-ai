"""Eval harness v1: the rule checks on the seed-42 golden set (no LLM).

Generates vendor-sim feeds (seed 42) for 2026-09-17 to 2026-09-25. The first
7 days are history: they fill the dedup window, so stale copies can be
caught. The last 2 days (200 labeled items) are scored. It runs the same
``RuleEngine`` as ``ai-api rules``, with an in-memory Redis, the SEC registry
fixture (``evals/datasets``) and ``python/config/sources.yaml``: no network.

Metrics:

- Duplicates: recall per labeled type (url, exact, near, stale; paraphrase
  is reported only: level L3 arrives in increment 3), precision (a false
  duplicate hides a real story) and link accuracy (the original found is
  the labeled one).
- Reason codes FAKE_COMPANY, FAKE_TICKER, SPOOFED_SOURCE, STALE: precision
  and recall against the labels.

Usage (inside the eval stage)::

    python -m evals.rules_eval             print the report
    python -m evals.rules_eval --check     also fail on a regression
    python -m evals.rules_eval --write-baseline

``--check`` fails when a gated metric is below its target or more than 2
points below ``evals/baseline.json``. The baseline only changes in a PR with
the ``eval-baseline-update`` label.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import dataclasses
import datetime
import json
import os
import pathlib
import sys
from typing import Any

import fakeredis
from vendor_sim import generator

from ai_api.dedup import config as dedup_config
from ai_api.dedup import fastpath
from ai_api.dedup import service
from ai_api.dedup import store
from ai_api.rules import checks
from ai_api.rules import engine
from ai_api.rules import registry

_HERE = pathlib.Path(__file__).resolve().parent
_BASELINE = _HERE / "baseline.json"
_REGISTRY = _HERE / "datasets" / "sec_company_tickers.json"
_SEED = 42
_FIRST_DAY = datetime.date(2026, 9, 17)
_SCORED_DAYS = (datetime.date(2026, 9, 24), datetime.date(2026, 9, 25))
_DUP_TYPES = ("url", "exact", "near", "stale", "paraphrase")
_MAX_DROP = 0.02
# Gated metrics and their floors. Paraphrases are reported, not gated.
TARGETS = {
    "dedup.precision": 0.99,
    "dedup.link_accuracy": 0.99,
    "dedup.recall.url": 1.0,
    "dedup.recall.exact": 1.0,
    "dedup.recall.near": 0.95,
    "dedup.recall.stale": 0.95,
    "FAKE_COMPANY.recall": 0.8,
    "FAKE_COMPANY.precision": 0.95,
    "FAKE_TICKER.recall": 0.8,
    "FAKE_TICKER.precision": 0.95,
    "SPOOFED_SOURCE.recall": 0.9,
    "SPOOFED_SOURCE.precision": 0.95,
    "STALE.recall": 0.9,
    "STALE.precision": 0.95,
}


@dataclasses.dataclass
class _Score:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def precision(self) -> float:
        return 1.0 if self.tp + self.fp == 0 else self.tp / (self.tp + self.fp)

    def recall(self) -> float:
        return 1.0 if self.tp + self.fn == 0 else self.tp / (self.tp + self.fn)


def _config_dir() -> pathlib.Path:
    configured = os.environ.get("PREMARKET_CONFIG_DIR", "").strip()
    if configured:
        return pathlib.Path(configured)
    return _HERE.parents[1] / "config"


async def _run_engine() -> list[tuple[engine.ItemResult, generator.Label]]:
    """Checks every day in order; returns the scored days' results."""
    cfg = dedup_config.DedupConfig()
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    dedup = service.DedupService(store.DedupStore(redis, cfg.ttl_s), cfg)
    sec = registry.Registry(
        registry.parse_sec_json(_REGISTRY.read_bytes()),
        datetime.datetime(2026, 9, 20, tzinfo=datetime.UTC),
    )
    policy = checks.SourcePolicy.from_yaml(_config_dir() / "sources.yaml")
    rules = engine.RuleEngine(dedup, sec, policy)
    scored: list[tuple[engine.ItemResult, generator.Label]] = []
    next_id = 1
    day = _FIRST_DAY
    while day <= _SCORED_DAYS[-1]:
        feed = generator.generate_feed(day, _SEED)
        labels = {label.id: label for label in feed.labels}
        items = []
        for item in sorted(feed.items, key=lambda i: i.id):
            items.append(
                engine.RawItem(
                    news_id=next_id,
                    feed_date=day,
                    vendor_item_id=item.id,
                    headline=item.headline,
                    body=item.body,
                    source_url=item.source_url,
                    source_domain=item.source_domain,
                    tickers=tuple(item.tickers),
                )
            )
            next_id += 1
        results = await rules.check_items(items)
        if day in _SCORED_DAYS:
            scored += [(r, labels[r.item.vendor_item_id]) for r in results]
        day += datetime.timedelta(days=1)
    return scored


def _metrics(
    scored: list[tuple[engine.ItemResult, generator.Label]],
) -> tuple[dict[str, float], dict[str, Any]]:
    dedup = _Score()
    links_ok = 0
    per_type = collections.Counter()
    per_type_hit = collections.Counter()
    codes = {code: _Score() for code in engine.REASON_ORDER}
    misses: list[str] = []
    for result, label in scored:
        predicted = result.duplicate is not None
        labeled = label.kind == "duplicate"
        if labeled:
            per_type[label.dup_type] += 1
        if predicted and labeled:
            dedup.tp += 1
            per_type_hit[label.dup_type] += 1
            if result.duplicate.canonical_vendor_item_id == label.dup_of:
                links_ok += 1
        elif predicted:
            dedup.fp += 1
            misses.append(f"false duplicate {label.id} ({label.subtype})")
        elif labeled and label.dup_type != "paraphrase":
            dedup.fn += 1
            misses.append(f"missed {label.dup_type} copy {label.id}")
        expected = set(label.reason_codes)
        for code, score in codes.items():
            hit = code in result.reason_codes
            if hit and code in expected:
                score.tp += 1
            elif hit:
                score.fp += 1
                misses.append(f"false {code} on {label.id} ({label.subtype})")
            elif code in expected:
                score.fn += 1
                misses.append(f"missed {code} on {label.id} ({label.subtype})")
    metrics = {
        "dedup.precision": dedup.precision(),
        "dedup.link_accuracy": links_ok / dedup.tp if dedup.tp else 1.0,
    }
    for dup_type in _DUP_TYPES:
        total = per_type[dup_type]
        metrics[f"dedup.recall.{dup_type}"] = (
            per_type_hit[dup_type] / total if total else 1.0
        )
    for code, score in codes.items():
        metrics[f"{code}.precision"] = score.precision()
        metrics[f"{code}.recall"] = score.recall()
    details = {
        "items": len(scored),
        "duplicates_by_type": dict(sorted(per_type.items())),
        "reason_code_support": {
            code: score.tp + score.fn for code, score in codes.items()
        },
        "misses": misses,
        "backend": fastpath.backend(),
    }
    return {k: round(v, 4) for k, v in metrics.items()}, details


def _gate(metrics: dict[str, float], baseline: dict[str, float]) -> list[str]:
    failures = []
    for name, floor in TARGETS.items():
        value = metrics[name]
        if value < floor:
            failures.append(f"{name} = {value:.4f} is below the target {floor}")
        base = baseline.get(name)
        if base is not None and value < base - _MAX_DROP:
            failures.append(
                f"{name} = {value:.4f} dropped more than {_MAX_DROP:.2f} "
                f"from the baseline {base:.4f}"
            )
    return failures


def _print_report(
    metrics: dict[str, float],
    details: dict[str, Any],
    baseline: dict[str, float],
) -> None:
    print(
        f"rule eval: {details['items']} scored items "
        f"({', '.join(d.isoformat() for d in _SCORED_DAYS)}), seed {_SEED}, "
        f"fastpath {details['backend']}"
    )
    print(f"  duplicates by type: {details['duplicates_by_type']}")
    print(f"  reason-code support: {details['reason_code_support']}")
    print(f"  {'metric':<26} {'value':>7} {'target':>7} {'baseline':>9}")
    for name, value in metrics.items():
        target = TARGETS.get(name)
        base = baseline.get(name)
        print(
            f"  {name:<26} {value:>7.4f} "
            f"{'-' if target is None else f'{target:.2f}':>7} "
            f"{'-' if base is None else f'{base:.4f}':>9}"
        )
    for miss in details["misses"]:
        print(f"  - {miss}")


def main(argv: list[str] | None = None) -> int:
    """Runs the eval.

    Args:
        argv: Command-line arguments; None means ``sys.argv[1:]``.

    Returns:
        The exit code: 1 when ``--check`` finds a regression.
    """
    parser = argparse.ArgumentParser(prog="rules_eval")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(argv)

    metrics, details = _metrics(asyncio.run(_run_engine()))
    baseline = {}
    if _BASELINE.exists():
        baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))["metrics"]
    _print_report(metrics, details, baseline)
    if args.write_baseline:
        document = {"eval": "rules_eval", "seed": _SEED, "metrics": metrics}
        _BASELINE.write_text(json.dumps(document, indent=2) + "\n")
        print(f"baseline written: {_BASELINE}")
    if args.check:
        failures = _gate(metrics, baseline)
        for failure in failures:
            print(f"FAIL {failure}")
        if failures:
            return 1
        print("PASS every gated metric")
    return 0


if __name__ == "__main__":
    sys.exit(main())
