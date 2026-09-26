"""The local model benchmark: which main model for the ``gpu4gb`` profile.

Every candidate (the gateway's ``bench-*`` aliases) gets the same 50
labeled vendor-sim items (seed 42, 2026-09-24/25: 22 real, 16 FAKE, 12
MISLEADING originals) and does the increment 3 work plus a preview of
increment 4's:

- ``extract`` (companies, tickers, claims) and ``summary`` (summary and
  sentiment): the real increment 3 prompts, structured output.
- ``verdict``: VERIFIED / UNVERIFIED / MISLEADING / FAKE from the text
  alone (no tools, no evidence yet), scored against the labels.
- ``tool call``: asked to look the company up, does it call the tool?
  (10 items; increment 4's agents need it.)

Measured: verdict accuracy and macro-F1, extracted-ticker recall, the
structured-output and tool-call success rates, output tokens/s, the VRAM
Ollama reports for the loaded model, and the time for 100 items (extract +
summary, sequential). Each model gets one warm-up call first, so model
loading isn't timed.

Writes ``local-models-<profile>.md`` and ``.json`` to ``--out``
(``docs/benchmarks`` through ``make -C python bench-models``).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime
import json
import os
import pathlib
import sys
import time
from typing import Any, Literal
import urllib.request

from langchain_core import tools
import pydantic
from vendor_sim import generator

from ai_api.enrich import chains
from ai_api.enrich import models
from ai_api.enrich import prompts
from ai_api.guard import sanitize
from ai_api.guard import spotlight
from ai_api.llm import config as llm_config
from ai_api.llm import factory

CANDIDATES = (
    ("bench-qwen3-4b", "Qwen3 4B Instruct 2507", "qwen3:4b-instruct"),
    ("bench-llama3.2-3b", "Llama 3.2 3B", "llama3.2:3b"),
    ("bench-phi4-mini", "Phi-4-mini 3.8B", "phi4-mini"),
    ("bench-gemma3-4b", "Gemma 3 4B", "gemma3:4b"),
)
VERDICTS = ("VERIFIED", "UNVERIFIED", "MISLEADING", "FAKE")
_DAYS = (datetime.date(2026, 9, 24), datetime.date(2026, 9, 25))
_PICK = {"real": 22, "fake": 16, "misleading": 12}
_TOOL_ITEMS = 10

VERDICT_SYSTEM = f"""\
You check one news item for a trading desk, from its text alone.
{spotlight.DATA_RULES}

Return JSON with:
- verdict: VERIFIED (plausible, specific, from a normal company
  announcement), UNVERIFIED (can't tell), MISLEADING (true facts presented
  in a misleading way, for example old news or cherry-picked numbers) or
  FAKE (invented, sensational or impossible).
- reason: one short sentence."""


class Verdict(pydantic.BaseModel):
    """A verdict from the text alone."""

    verdict: Literal["VERIFIED", "UNVERIFIED", "MISLEADING", "FAKE"]
    reason: str


@tools.tool
def lookup_company(ticker: str) -> str:
    """Looks up a company in the SEC ticker registry by its ticker."""
    return f"{ticker}: not looked up in the benchmark"


@dataclasses.dataclass
class _Tally:
    calls: int = 0
    parsed: int = 0
    seconds: float = 0.0
    output_tokens: int = 0


def _items() -> list[tuple[Any, Any]]:
    picked = []
    counts = dict.fromkeys(_PICK, 0)
    for day in _DAYS:
        feed = generator.generate_feed(day, 42)
        for item, label in sorted(
            zip(feed.items, feed.labels, strict=True), key=lambda p: p[0].id
        ):
            kind = label.kind
            if kind in counts and counts[kind] < _PICK[kind]:
                counts[kind] += 1
                picked.append((item, label))
    return picked


def _macro_f1(pairs: list[tuple[str, str]]) -> float:
    scores = []
    for verdict in VERDICTS:
        tp = sum(1 for p, e in pairs if p == verdict and e == verdict)
        fp = sum(1 for p, e in pairs if p == verdict and e != verdict)
        fn = sum(1 for p, e in pairs if p != verdict and e == verdict)
        if tp + fp + fn == 0:
            continue
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        denominator = precision + recall
        scores.append(
            0 if denominator == 0 else 2 * precision * recall / denominator
        )
    return sum(scores) / len(scores) if scores else 0.0


def _vram_mib(ollama_url: str, tag: str) -> int | None:
    if not ollama_url:
        return None
    try:
        with urllib.request.urlopen(f"{ollama_url}/api/ps", timeout=5) as r:
            data = json.load(r)
    except OSError:
        return None
    for model in data.get("models", []):
        if model.get("name", "").split(":latest")[0] == tag.split(":latest")[0]:
            return int(model.get("size_vram", 0) / 2**20)
    return None


async def _structured(
    model: Any, schema: type, system: str, user: str, tally: _Tally
) -> Any:
    runnable = model.with_structured_output(
        schema, method="json_schema", include_raw=True
    )
    started = time.monotonic()
    tally.calls += 1
    try:
        result = await runnable.ainvoke([("system", system), ("human", user)])
    except Exception:  # noqa: BLE001 - a failed call is a failed parse.
        tally.seconds += time.monotonic() - started
        return None
    tally.seconds += time.monotonic() - started
    raw = result.get("raw")
    usage = getattr(raw, "usage_metadata", None) or {}
    tally.output_tokens += int(usage.get("output_tokens", 0))
    if result.get("parsing_error") is None and result.get("parsed") is not None:
        tally.parsed += 1
        return result["parsed"]
    return None


async def _bench(
    llm: llm_config.LlmConfig, alias: str, tag: str, items: list[Any]
) -> dict[str, Any]:
    model = factory.chat_model(llm, model=alias, max_tokens=700)
    await model.ainvoke("Reply with: ok")  # warm-up: load the model
    vram = _vram_mib(os.environ.get("OLLAMA_BASE_URL", ""), tag)
    work = _Tally()
    verdict_tally = _Tally()
    pairs = []
    ticker_hits = ticker_total = 0
    for item, label in items:
        clean = sanitize.sanitize(item.headline, item.body)
        user = prompts.item_message(clean.headline, clean.body, item.id)
        extraction = await _structured(
            model, models.Extraction, prompts.EXTRACT_SYSTEM, user, work
        )
        await _structured(
            model, models.Summary, prompts.SUMMARY_SYSTEM, user, work
        )
        expected = {t.upper() for t in item.tickers}
        ticker_total += len(expected)
        if extraction is not None:
            found = {
                c.ticker
                for c in chains.clean_extraction(extraction).companies
                if c.ticker
            }
            ticker_hits += len(expected & found)
        verdict = await _structured(
            model, Verdict, VERDICT_SYSTEM, user, verdict_tally
        )
        predicted = "INVALID" if verdict is None else verdict.verdict
        pairs.append((predicted, label.expected_verdict))
    tool_ok = 0
    with_tools = model.bind_tools([lookup_company])
    for item, _ in items[:_TOOL_ITEMS]:
        clean = sanitize.sanitize(item.headline, item.body)
        try:
            reply = await with_tools.ainvoke(
                [
                    (
                        "system",
                        "Use the lookup_company tool to check the company "
                        "this item names. " + spotlight.DATA_RULES,
                    ),
                    (
                        "human",
                        spotlight.news_block(clean.headline, clean.body),
                    ),
                ]
            )
        except Exception:  # noqa: BLE001 - no tool support is a failure.
            continue
        calls = getattr(reply, "tool_calls", []) or []
        if any(c.get("args", {}).get("ticker") for c in calls):
            tool_ok += 1
    correct = sum(1 for p, e in pairs if p == e)
    per_item = work.seconds / len(items)
    return {
        "alias": alias,
        "ollama_tag": tag,
        "verdict_accuracy": round(correct / len(pairs), 4),
        "verdict_macro_f1": round(_macro_f1(pairs), 4),
        "ticker_recall": round(ticker_hits / ticker_total, 4)
        if ticker_total
        else 1.0,
        "structured_success": round(
            (work.parsed + verdict_tally.parsed)
            / (work.calls + verdict_tally.calls),
            4,
        ),
        "tool_call_success": round(tool_ok / min(_TOOL_ITEMS, len(items)), 4),
        "tokens_per_s": round(work.output_tokens / work.seconds, 1)
        if work.seconds
        else 0.0,
        "vram_mib": vram,
        "seconds_per_item": round(per_item, 2),
        "minutes_per_100_items": round(per_item * 100 / 60, 1),
    }


def _pick_winner(rows: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [r for r in rows if r["structured_success"] >= 0.95] or rows
    return max(
        usable,
        key=lambda r: (
            round((r["verdict_macro_f1"] + r["ticker_recall"]) / 2, 2),
            -r["minutes_per_100_items"],
        ),
    )


def _markdown(rows: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    names = {alias: name for alias, name, _ in CANDIDATES}
    winner = meta["winner"]
    lines = [
        f"# Local model benchmark: `{meta['profile']}`",
        "",
        f"Run {meta['date']} on the GPU host through the LLM gateway. "
        f"{meta['items']} labeled vendor-sim items (seed 42, "
        "2026-09-24/25: 22 real, 16 FAKE, 12 MISLEADING). Command: "
        "`make -C python bench-models`.",
        "",
        "| Model | Verdict acc. | Verdict macro-F1 | Ticker recall | "
        "Structured output | Tool calls | Tokens/s | VRAM (MiB) | "
        "Min / 100 items |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        mark = " **(winner)**" if r["alias"] == winner else ""
        lines.append(
            f"| {names[r['alias']]} (`{r['ollama_tag']}`){mark} | "
            f"{r['verdict_accuracy']:.2f} | {r['verdict_macro_f1']:.2f} | "
            f"{r['ticker_recall']:.2f} | {r['structured_success']:.2f} | "
            f"{r['tool_call_success']:.2f} | {r['tokens_per_s']} | "
            f"{r['vram_mib'] if r['vram_mib'] is not None else '-'} | "
            f"{r['minutes_per_100_items']} |"
        )
    lines += [
        "",
        "- **Verdict** is from the text alone (no tools or evidence yet); "
        "increment 4 adds the checks, so it only compares the models.",
        "- **Min / 100 items**: extract + summary, one call at a time "
        "(the AI run keeps two in flight).",
        "- **Winner**: structured output >= 0.95, then the best average of "
        "verdict macro-F1 and ticker recall, then the fastest. It is pinned "
        "as `main-gpu4gb` in `podman/config/litellm/config.yaml`.",
        "",
    ]
    return "\n".join(lines)


async def _run(out: pathlib.Path, only: list[str] | None) -> int:
    llm = llm_config.LlmConfig.from_env(os.environ)
    items = _items()
    rows = []
    for alias, name, tag in CANDIDATES:
        if only and alias not in only:
            continue
        print(f"== {name} ({alias})", flush=True)
        row = await _bench(llm, alias, tag, items)
        print(json.dumps(row), flush=True)
        rows.append(row)
    meta = {
        "profile": llm.hw_profile,
        "date": datetime.date.today().isoformat(),
        "items": len(items),
        "winner": _pick_winner(rows)["alias"],
    }
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"local-models-{llm.hw_profile}"
    stem.with_suffix(".json").write_text(
        json.dumps({"meta": meta, "results": rows}, indent=2) + "\n"
    )
    stem.with_suffix(".md").write_text(_markdown(rows, meta))
    print(f"winner: {meta['winner']}; written {stem}.md/.json")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Runs the benchmark.

    Args:
        argv: Command-line arguments; None means ``sys.argv[1:]``.

    Returns:
        The exit code.
    """
    parser = argparse.ArgumentParser(prog="bench_models")
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--only", nargs="*", help="aliases to run")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.out, args.only))


if __name__ == "__main__":
    sys.exit(main())
