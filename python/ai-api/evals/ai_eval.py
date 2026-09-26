"""Eval of the increment 3 layers before the model: L3 and the guard.

Runs the rules on the seed-42 golden set (2026-09-17 to 2026-09-25, the same
feeds as ``rules_eval``), embeds the items they found unique through the
LLM gateway, and runs the AI pipeline up to the model steps (sanitize,
L3, language). Scored on 2026-09-24/25:

- ``l3.recall.paraphrase``: labeled paraphrases linked to their original.
- ``l3.precision``: L3 links that are labeled duplicates (a false duplicate
  hides a real story).
- ``l3.link_accuracy``: the original found is the labeled one.
- ``INJECTION_ATTEMPT.recall`` / ``.precision`` against the labels.
- ``language.false_flags``: English items flagged UNSUPPORTED_LANGUAGE.
- Reported only: conflicting versions (evidence, no badge) by label kind.

Needs the gateway (the GPU host's embedding model), so it runs in the
``ai-eval`` container on the compose network: ``make -C python eval-ai``.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import pathlib
import sys
from typing import Any

from ai_api.dedup import config as dedup_config
from ai_api.dedup import paraphrase
from ai_api.enrich import runner
from ai_api.guard import language
from ai_api.guard import sanitize
from ai_api.llm import config as llm_config
from ai_api.llm import factory
from ai_api.llm import tracing
from evals import rules_eval

_HERE = pathlib.Path(__file__).resolve().parent
_BASELINE = _HERE / "ai_baseline.json"
_MAX_DROP = 0.02
TARGETS = {
    "l3.recall.paraphrase": 0.85,
    "l3.precision": 0.95,
    "l3.link_accuracy": 0.95,
    "INJECTION_ATTEMPT.recall": 1.0,
    "INJECTION_ATTEMPT.precision": 0.95,
}


async def _outcomes() -> tuple[list[Any], dict[int, Any]]:
    results = await rules_eval.run_engine(all_days=True)
    unique = [(r.item, label) for r, label in results if r.duplicate is None]
    llm = llm_config.LlmConfig.from_env(os.environ)
    vectors = await runner.embed_items(
        factory.embeddings(llm),
        [item for item, _ in unique],
        {},
        llm.cluster_prefix,
    )
    pipeline = runner.Pipeline(
        l3=paraphrase.ParaphraseCheck(
            paraphrase.MemoryVectorIndex(),
            dedup_config.DedupConfig.from_env(os.environ),
        ),
        enricher=None,
        tracer=tracing.Tracer(tracing.TracingConfig()),
    )
    outcomes = await pipeline.run(
        [item for item, _ in unique], vectors, skip_models=True
    )
    labels = {item.news_id: label for item, label in unique}
    scored_days = set(rules_eval._SCORED_DAYS)  # noqa: SLF001
    items = {item.news_id: item for item, _ in unique}
    scored = [
        (o, labels[o.news_id])
        for o in outcomes
        if items[o.news_id].feed_date in scored_days
    ]
    rule_dups = [
        (r, label)
        for r, label in results
        if r.duplicate is not None and r.item.feed_date in scored_days
    ]
    return scored, {"rule_dups": rule_dups}


def _metrics(
    scored: list[Any], extra: dict[str, Any]
) -> tuple[dict[str, float], dict[str, Any]]:
    tp = fp = links_ok = 0
    paraphrases = sum(
        1 for _, label in scored if label.dup_type == "paraphrase"
    )
    # A paraphrase the rules already linked (L0-L2) counts as found too.
    paraphrases += sum(
        1 for _, label in extra["rule_dups"] if label.dup_type == "paraphrase"
    )
    found = sum(
        1 for _, label in extra["rule_dups"] if label.dup_type == "paraphrase"
    )
    injection = rules_eval._Score()  # noqa: SLF001
    language_false = 0
    conflicts = collections.Counter()
    misses = []
    for outcome, label in scored:
        if outcome.duplicate is not None:
            if label.kind == "duplicate":
                tp += 1
                found += label.dup_type == "paraphrase"
                if outcome.duplicate.canonical_vendor_item_id == label.dup_of:
                    links_ok += 1
            else:
                fp += 1
                misses.append(
                    f"false L3 duplicate {label.id} ({label.subtype})"
                )
        elif label.dup_type == "paraphrase":
            misses.append(f"missed paraphrase {label.id}")
        hit = sanitize.INJECTION_ATTEMPT in outcome.reason_codes
        expected = sanitize.INJECTION_ATTEMPT in label.reason_codes
        if hit and expected:
            injection.tp += 1
        elif hit:
            injection.fp += 1
            misses.append(f"false INJECTION_ATTEMPT on {label.id}")
        elif expected:
            injection.fn += 1
            misses.append(f"missed INJECTION_ATTEMPT on {label.id}")
        if language.UNSUPPORTED_LANGUAGE in outcome.reason_codes:
            language_false += 1
            misses.append(f"false UNSUPPORTED_LANGUAGE on {label.id}")
        if outcome.conflict:
            conflicts[f"{label.kind}/{label.subtype}"] += 1
    metrics = {
        "l3.recall.paraphrase": found / paraphrases if paraphrases else 1.0,
        "l3.precision": tp / (tp + fp) if tp + fp else 1.0,
        "l3.link_accuracy": links_ok / tp if tp else 1.0,
        "INJECTION_ATTEMPT.recall": injection.recall(),
        "INJECTION_ATTEMPT.precision": injection.precision(),
        "language.false_flags": float(language_false),
    }
    details = {
        "items": len(scored),
        "paraphrases": paraphrases,
        "conflicting_versions": dict(sorted(conflicts.items())),
        "misses": misses,
    }
    return {k: round(v, 4) for k, v in metrics.items()}, details


def _gate(metrics: dict[str, float], baseline: dict[str, float]) -> list[str]:
    failures = []
    for name, floor in TARGETS.items():
        if metrics[name] < floor:
            failures.append(f"{name} = {metrics[name]:.4f} is below {floor}")
        base = baseline.get(name)
        if base is not None and metrics[name] < base - _MAX_DROP:
            failures.append(f"{name} dropped from the baseline {base:.4f}")
    if metrics["language.false_flags"] > 0:
        failures.append("English items were flagged UNSUPPORTED_LANGUAGE")
    return failures


def main(argv: list[str] | None = None) -> int:
    """Runs the eval.

    Args:
        argv: Command-line arguments; None means ``sys.argv[1:]``.

    Returns:
        The exit code: 1 when ``--check`` finds a regression.
    """
    parser = argparse.ArgumentParser(prog="ai_eval")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(argv)

    scored, extra = asyncio.run(_outcomes())
    metrics, details = _metrics(scored, extra)
    baseline = {}
    if _BASELINE.exists():
        baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))["metrics"]
    print(
        f"AI eval (L3 + guard): {details['items']} unique scored items, "
        f"{details['paraphrases']} labeled paraphrases, seed "
        f"{rules_eval._SEED}"  # noqa: SLF001
    )
    for name, value in metrics.items():
        target = TARGETS.get(name)
        print(
            f"  {name:<30} {value:>7.4f} "
            f"{'-' if target is None else f'{target:.2f}':>6}"
        )
    print(f"  conflicting versions: {details['conflicting_versions']}")
    for miss in details["misses"]:
        print(f"  - {miss}")
    if args.write_baseline:
        document = {"eval": "ai_eval", "seed": 42, "metrics": metrics}
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
