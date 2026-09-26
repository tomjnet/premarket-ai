"""ChromaDB -> pgvector migration (increment 6): re-embed, compare, report.

``make -C python migrate-vectors`` runs this in the ``ai-eval`` container
(it has the eval questions and reaches the gateway, chroma and Postgres):

1. Re-embeds every ``ai.chunk`` row into ``ai.chunk.embedding`` with the same
   embedding model the ChromaDB collection was built with (the column is
   resized first when the model's size differs).
2. For every question of ``evals/datasets/rag_questions.jsonl``, retrieves
   the top ``RAG_TOP_K`` chunks from ChromaDB, from pgvector (vector only)
   and from pgvector hybrid (vector + full text, the default), and compares
   the chunk ids: overlap@k (shared ids / k) and overlap@n (``RAG_TOP_N``,
   what reaches the model after the reranker when it's down).
3. Writes ``vector-migration-<profile>.md`` / ``.json`` to ``--out``.

With ``--check`` it fails when the vector-only overlap@k is under
``--min-overlap`` (default 0.9): the same vectors must find the same
neighbours, whatever the index. Hybrid is expected to differ; that it
answers at least as well is what ``make -C python eval-rag`` (RAGAS
faithfulness and context precision) shows afterwards. The Makefile then
sets ``VECTOR_STORE=pgvector`` in ``.env``.
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
import time
from typing import Any

import psycopg

from ai_api import config
from ai_api.llm import config as llm_config
from ai_api.llm import factory
from ai_api.rag import config as rag_config
from ai_api.rag import corpus
from ai_api.rag import store

_HERE = pathlib.Path(__file__).resolve().parent
_QUESTIONS = _HERE / "datasets" / "rag_questions.jsonl"


def _questions() -> list[str]:
    return [
        json.loads(line)["question"]
        for line in _QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _overlap(left: list[int], right: list[int], k: int) -> float:
    if k == 0:
        return 1.0
    return len(set(left[:k]) & set(right[:k])) / k


async def _timed(search: Any, question: str, k: int) -> tuple[list[int], float]:
    started = time.perf_counter()
    hits = await search(question, k)
    return [h.chunk_id for h in hits], (time.perf_counter() - started) * 1000


async def _migrate(
    settings: config.AiSettings, questions: list[str]
) -> dict[str, Any]:
    llm = settings.llm
    rag = settings.rag
    embeddings = store.PrefixedEmbeddings(
        factory.embeddings(llm), llm.query_prefix, llm.document_prefix
    )
    async with await psycopg.AsyncConnection.connect(
        settings.owner.dsn(), autocommit=True
    ) as conn:
        repo = corpus.CorpusRepository(conn)
        connect = store.connection_of(conn)
        vectors = store.PgVectorStore(
            connect, embeddings, llm.embed_model, llm.embed_dims, hybrid=False
        )
        hybrid = store.PgVectorStore(
            connect, embeddings, llm.embed_model, llm.embed_dims, hybrid=True
        )
        chroma = store.ChromaStore(rag, embeddings, llm.embed_model)
        started = time.perf_counter()
        try:
            indexed = await corpus.index(repo, vectors, llm.embed_model)
        except store.StoreMismatchError as e:
            print(f"resizing ai.chunk.embedding: {e}", flush=True)
            await vectors.reset()
            indexed = await corpus.index(repo, vectors, llm.embed_model)
        embed_s = time.perf_counter() - started
        print(f"embedded {indexed} chunks in {embed_s:.0f} s", flush=True)
        rows = []
        for question in questions:
            chroma_ids, chroma_ms = await _timed(
                chroma.search, question, rag.top_k
            )
            vector_ids, vector_ms = await _timed(
                vectors.search, question, rag.top_k
            )
            hybrid_ids, hybrid_ms = await _timed(
                hybrid.search, question, rag.top_k
            )
            rows.append(
                {
                    "question": question,
                    "chroma": chroma_ids,
                    "pgvector": vector_ids,
                    "hybrid": hybrid_ids,
                    "ms": {
                        "chroma": chroma_ms,
                        "pgvector": vector_ms,
                        "hybrid": hybrid_ms,
                    },
                }
            )
            print(
                f"{_overlap(chroma_ids, vector_ids, rag.top_k):.2f} "
                f"{_overlap(chroma_ids, hybrid_ids, rag.top_k):.2f} "
                f"{question[:60]}",
                flush=True,
            )
        return {
            "rows": rows,
            "indexed": indexed,
            "embed_s": embed_s,
            "chroma_chunks": await chroma.count(),
            "pgvector_chunks": await vectors.count(),
        }


def _metrics(
    rows: list[dict[str, Any]], rag: rag_config.RagConfig
) -> dict[str, float]:
    def mean_overlap(other: str, k: int) -> float:
        return statistics.fmean(
            _overlap(r["chroma"], r[other], k) for r in rows
        )

    def median_ms(kind: str) -> float:
        return statistics.median(r["ms"][kind] for r in rows)

    return {
        "pgvector.overlap@k": mean_overlap("pgvector", rag.top_k),
        "pgvector.overlap@n": mean_overlap("pgvector", rag.top_n),
        "hybrid.overlap@k": mean_overlap("hybrid", rag.top_k),
        "hybrid.overlap@n": mean_overlap("hybrid", rag.top_n),
        "chroma.median_ms": median_ms("chroma"),
        "pgvector.median_ms": median_ms("pgvector"),
        "hybrid.median_ms": median_ms("hybrid"),
    }


def _markdown(meta: dict[str, Any], metrics: dict[str, float]) -> str:
    lines = [
        f"# Vector store migration: ChromaDB -> pgvector (`{meta['profile']}`)",
        "",
        f"Run {meta['date']}: {meta['pgvector_chunks']} chunks in pgvector "
        f"({meta['indexed']} embedded now, {meta['embed_s']:.0f} s) vs "
        f"{meta['chroma_chunks']} in ChromaDB, embedding model "
        f"`{meta['embed_model']}`, {meta['questions']} eval questions, "
        f"k = {meta['top_k']}, n = {meta['top_n']}. Command: "
        "`make -C python migrate-vectors`.",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    lines += [f"| {name} | {value:.2f} |" for name, value in metrics.items()]
    lines += [
        "",
        "- **overlap@k**: chunk ids both stores return in their top k, "
        "divided by k (1.00 = the same set). **@n**: the same for the top n.",
        "- **pgvector**: vector search only (HNSW, cosine). With the same "
        "embeddings it should find the same neighbours as ChromaDB's HNSW.",
        "- **hybrid**: pgvector's default, vector + Postgres full text fused "
        "by reciprocal rank. It is meant to differ (exact words such as "
        "tickers, form numbers and amounts count); `make -C python eval-rag` "
        "measures whether its answers are at least as good.",
        "- **median_ms**: one retrieval, embedding the question included.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Runs the migration and the comparison.

    Args:
        argv: Command-line arguments; None means ``sys.argv[1:]``.

    Returns:
        The exit code.
    """
    parser = argparse.ArgumentParser(prog="migrate_vectors")
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--min-overlap", type=float, default=0.9)
    args = parser.parse_args(argv)

    settings = config.AiSettings.from_env(os.environ)
    llm: llm_config.LlmConfig = settings.llm
    questions = _questions()
    result = asyncio.run(_migrate(settings, questions))
    measured = _metrics(result["rows"], settings.rag)
    metrics = {k: round(v, 4) for k, v in measured.items()}
    meta = {
        "profile": llm.hw_profile,
        "date": datetime.date.today().isoformat(),
        "embed_model": llm.embed_model,
        "questions": len(questions),
        "top_k": settings.rag.top_k,
        "top_n": settings.rag.top_n,
        "indexed": result["indexed"],
        "embed_s": round(result["embed_s"], 1),
        "chroma_chunks": result["chroma_chunks"],
        "pgvector_chunks": result["pgvector_chunks"],
    }
    for name, value in metrics.items():
        print(f"  {name:<22} {value:.4f}")
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.out / f"vector-migration-{llm.hw_profile}"
    stem.with_suffix(".json").write_text(
        json.dumps(
            {"meta": meta, "metrics": metrics, "rows": result["rows"]},
            indent=2,
        )
        + "\n"
    )
    stem.with_suffix(".md").write_text(_markdown(meta, metrics))
    print(f"written {stem}.md/.json")
    failed = []
    if result["pgvector_chunks"] < result["chroma_chunks"]:
        failed.append(
            f"pgvector has {result['pgvector_chunks']} chunks, ChromaDB"
            f" {result['chroma_chunks']}"
        )
    if metrics["pgvector.overlap@k"] < args.min_overlap:
        failed.append(
            f"pgvector.overlap@k {metrics['pgvector.overlap@k']:.2f}"
            f" < {args.min_overlap}"
        )
    if args.check and failed:
        print("FAILED: " + "; ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
