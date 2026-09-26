"""RAG eval: the RAGAS baseline of "Ask the News" (increment 3).

Asks every question of ``evals/datasets/rag_questions.jsonl`` through the
same chain as ``POST /chat`` (vector search, reranker, main model, citation
and advice checks) and scores:

- ``cites_trusted``: answers that cite at least one trusted source.
- ``advice_refused``: advice questions ("Should I buy ...?") that get a
  refusal instead of advice.
- The RAGAS metrics ``faithfulness`` (statements supported by the
  retrieved sources) and ``context_precision`` (useful sources ranked
  first, against the reference answer), judged by the main model through
  the gateway (``rag_metrics``: the ``ragas`` package doesn't import next
  to LangChain 1.x).

The questions are about the trusted corpus of the last 12 months, so build
it first (``make -C python corpus``). Runs in the ``ai-eval`` container:
``make -C python eval-rag``; writes ``rag-baseline-<profile>.md`` and
``.json`` to ``--out``.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import pathlib
import statistics
import sys
from typing import Any

from ai_api.llm import config as llm_config
from ai_api.llm import factory
from ai_api.llm import tracing
from ai_api.rag import ask
from ai_api.rag import config as rag_config
from ai_api.rag import rerank
from ai_api.rag import store
from ai_api.rag import universe
from evals import rag_metrics

_HERE = pathlib.Path(__file__).resolve().parent
_QUESTIONS = _HERE / "datasets" / "rag_questions.jsonl"


def _config_dir() -> pathlib.Path:
    configured = os.environ.get("PREMARKET_CONFIG_DIR", "").strip()
    if configured:
        return pathlib.Path(configured)
    return _HERE.parents[1] / "config"


def _service(llm: llm_config.LlmConfig) -> ask.AskService:
    rag = rag_config.RagConfig.from_env(os.environ)
    embeddings = store.PrefixedEmbeddings(
        factory.embeddings(llm), llm.query_prefix, llm.document_prefix
    )
    return ask.AskService(
        store=store.CorpusStore(rag, embeddings, llm.embed_model),
        reranker=rerank.Reranker(rag.reranker_url),
        model=factory.chat_model(llm, max_tokens=600),
        tracer=tracing.Tracer(tracing.TracingConfig()),
        cfg=rag,
        members=universe.load(_config_dir()),
        vendor_lookup=None,
        model_name=llm.main_model,
    )


async def _judged(
    llm: llm_config.LlmConfig, rows: list[dict[str, Any]]
) -> dict[str, float]:
    """RAGAS faithfulness and context precision (``rag_metrics``)."""
    judge = factory.chat_model(llm, max_tokens=1500)
    faithful: list[float] = []
    precise: list[float] = []
    failures = 0
    for row in rows:
        if row["advice"] or not row["contexts"]:
            continue
        try:
            score = await rag_metrics.faithfulness(
                judge, row["answer"], row["contexts"]
            )
            if score is not None:
                faithful.append(score)
            score = await rag_metrics.context_precision(
                judge, row["question"], row["reference"], row["contexts"]
            )
            if score is None:
                failures += 1
            else:
                precise.append(score)
        except Exception:  # noqa: BLE001 - a failed judgment is counted.
            failures += 1
    return {
        "ragas.faithfulness": statistics.fmean(faithful) if faithful else 0.0,
        "ragas.context_precision": statistics.fmean(precise)
        if precise
        else 0.0,
        "judge_failures": float(failures),
    }


async def _answers(llm: llm_config.LlmConfig) -> list[dict[str, Any]]:
    service = _service(llm)
    day = datetime.date.today()
    rows = []
    for line in _QUESTIONS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        question = json.loads(line)
        result: dict[str, Any] = {}
        # One retry: a model stream can break on the GPU host (a model
        # swap); a question that fails twice is counted, not fatal.
        for _attempt in range(2):
            try:
                result = await service.ask(question["question"], day)
                break
            except Exception as e:  # noqa: BLE001 - counted below.
                print(f"!! {question['question'][:60]}: {e!r}", flush=True)
        rows.append(
            {
                "question": question["question"],
                "reference": question.get("reference", ""),
                "advice": question.get("advice", False),
                "answer": result.get("answer", ""),
                "citations": result.get("citations", []),
                "cites_trusted": result.get("cites_trusted", False),
                "refused": result.get("refused", False)
                or "investment advice" in result.get("answer", "").lower(),
                "contexts": [s["text"] for s in result.get("sources", [])],
                "elapsed_ms": result.get("elapsed_ms", 0),
                "reranked": result.get("reranked", False),
                "failed": not result,
            }
        )
        print(
            f"{'OK ' if rows[-1]['cites_trusted'] else '-- '}"
            f"{question['question'][:70]}",
            flush=True,
        )
    return rows


def _markdown(meta: dict[str, Any], metrics: dict[str, float]) -> str:
    lines = [
        f"# RAG baseline: `{meta['profile']}`",
        "",
        f"Run {meta['date']}: {meta['questions']} questions "
        f"(`python/ai-api/evals/datasets/rag_questions.jsonl`) through the "
        f'"Ask the News" chain, main model `{meta["model"]}`, corpus of '
        f"{meta['corpus_chunks']} chunks. Command: `make -C python eval-rag`.",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    lines += [f"| {name} | {value:.2f} |" for name, value in metrics.items()]
    lines += [
        "",
        "- **cites_trusted**: answers citing at least one trusted source "
        "(SEC, Fed).",
        "- **advice_refused**: advice questions answered with a refusal.",
        "- **reranked**: answers whose sources the reranker ordered (else "
        "vector order); **answer_failures**: questions that failed twice.",
        "- **ragas.***: judged by the same local model, so they compare runs "
        "of this lab, not models from other labs.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Runs the eval.

    Args:
        argv: Command-line arguments; None means ``sys.argv[1:]``.

    Returns:
        The exit code.
    """
    parser = argparse.ArgumentParser(prog="rag_eval")
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--no-judge", action="store_true")
    args = parser.parse_args(argv)

    llm = llm_config.LlmConfig.from_env(os.environ)
    rows = asyncio.run(_answers(llm))
    factual = [r for r in rows if not r["advice"]]
    advice = [r for r in rows if r["advice"]]
    metrics = {
        "cites_trusted": sum(r["cites_trusted"] for r in factual)
        / max(len(factual), 1),
        "advice_refused": sum(r["refused"] for r in advice)
        / max(len(advice), 1),
        "reranked": sum(r["reranked"] for r in rows) / max(len(rows), 1),
        "answer_failures": float(sum(r["failed"] for r in rows)),
    }
    if not args.no_judge:
        metrics.update(asyncio.run(_judged(llm, rows)))
    rag = rag_config.RagConfig.from_env(os.environ)
    meta = {
        "profile": llm.hw_profile,
        "date": datetime.date.today().isoformat(),
        "questions": len(rows),
        "model": llm.main_model,
        "corpus_chunks": store.CorpusStore(
            rag, factory.embeddings(llm), llm.embed_model
        ).count(),
    }
    metrics = {k: round(v, 4) for k, v in metrics.items()}
    for name, value in metrics.items():
        print(f"  {name:<26} {value:.4f}")
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.out / f"rag-baseline-{llm.hw_profile}"
    stem.with_suffix(".json").write_text(
        json.dumps({"meta": meta, "metrics": metrics, "rows": rows}, indent=2)
        + "\n"
    )
    stem.with_suffix(".md").write_text(_markdown(meta, metrics))
    print(f"written {stem}.md/.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
