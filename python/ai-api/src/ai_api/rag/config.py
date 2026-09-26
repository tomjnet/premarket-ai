"""RAG settings: the vector store, the reranker and the corpus size."""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses

VECTOR_STORES = ("chroma",)


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from e
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


@dataclasses.dataclass(frozen=True)
class RagConfig:
    """Where the vectors are and how much to retrieve.

    Attributes:
        vector_store: VECTOR_STORE: ``chroma`` in increments 3 to 5
            (``pgvector`` arrives in increment 6).
        chroma_host: CHROMA_HOST.
        chroma_port: CHROMA_PORT.
        collection: The corpus collection (``trusted_corpus``).
        reranker_url: RERANKER_URL, the cross-encoder service; empty means
            no reranking (vector order).
        top_k: RAG_TOP_K: candidates from the vector search.
        top_n: RAG_TOP_N: sources kept after reranking.
        corpus_months: CORPUS_MONTHS: how far back filings and releases go.
        max_filings: CORPUS_MAX_FILINGS: newest 8-Ks per company.
        max_releases: CORPUS_MAX_RELEASES: newest Fed and SEC releases each.
        chunk_chars: Target chunk size in characters.
        chunk_overlap: Characters repeated between neighboring chunks.
    """

    vector_store: str = "chroma"
    chroma_host: str = "chroma"
    chroma_port: int = 8000
    collection: str = "trusted_corpus"
    reranker_url: str = "http://reranker:8080"
    top_k: int = 20
    top_n: int = 5
    corpus_months: int = 12
    max_filings: int = 8
    max_releases: int = 40
    chunk_chars: int = 1500
    chunk_overlap: int = 200

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> RagConfig:
        """Reads the RAG settings; missing ones keep the defaults.

        Raises:
            ValueError: A value is invalid.
        """
        store = env.get("VECTOR_STORE", "chroma").strip().lower()
        if store not in VECTOR_STORES:
            raise ValueError(
                f"VECTOR_STORE must be one of {', '.join(VECTOR_STORES)} in "
                f"this increment, got {store!r}"
            )
        top_k = _int(env, "RAG_TOP_K", 20)
        top_n = _int(env, "RAG_TOP_N", 5)
        if top_n > top_k:
            raise ValueError("RAG_TOP_N must be <= RAG_TOP_K")
        return cls(
            vector_store=store,
            chroma_host=env.get("CHROMA_HOST", "chroma").strip(),
            chroma_port=_int(env, "CHROMA_PORT", 8000),
            reranker_url=env.get("RERANKER_URL", "http://reranker:8080")
            .strip()
            .rstrip("/"),
            top_k=top_k,
            top_n=top_n,
            corpus_months=_int(env, "CORPUS_MONTHS", 12),
            max_filings=_int(env, "CORPUS_MAX_FILINGS", 8),
            max_releases=_int(env, "CORPUS_MAX_RELEASES", 40),
        )
