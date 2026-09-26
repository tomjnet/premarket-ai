"""The RAG vector store, behind LangChain's ``VectorStore`` interface.

Increments 3 to 5 use ChromaDB (``langchain-chroma`` with the thin HTTP
client); increment 6 swaps in pgvector behind the same functions
(``VECTOR_STORE``). The store is only an index: Postgres keeps the chunk
text (``ai.chunk``) and ``make -C python reindex`` rebuilds it. Document
ids are the ``ai.chunk`` ids.
"""

from __future__ import annotations

from collections.abc import Sequence
import contextlib
import dataclasses
from typing import Any

import chromadb
import langchain_chroma
from langchain_core import documents as lc_documents
from langchain_core import embeddings as lc_embeddings
from langchain_core import vectorstores

from ai_api.rag import config


class StoreMismatchError(RuntimeError):
    """The collection was built with another embedding model."""


class PrefixedEmbeddings(lc_embeddings.Embeddings):
    """Adds the embedding model's task prefixes (nomic-embed-text)."""

    def __init__(
        self,
        inner: lc_embeddings.Embeddings,
        query_prefix: str,
        document_prefix: str,
    ) -> None:
        """Wraps ``inner``."""
        self._inner = inner
        self._query = query_prefix
        self._document = document_prefix

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embeds documents with the document prefix."""
        return self._inner.embed_documents([self._document + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        """Embeds a query with the query prefix."""
        return self._inner.embed_query(self._query + text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embeds documents with the document prefix."""
        return await self._inner.aembed_documents(
            [self._document + t for t in texts]
        )

    async def aembed_query(self, text: str) -> list[float]:
        """Embeds a query with the query prefix."""
        return await self._inner.aembed_query(self._query + text)


@dataclasses.dataclass(frozen=True)
class Hit:
    """A retrieved chunk.

    Attributes:
        chunk_id: The ``ai.chunk`` id.
        text: The chunk text.
        metadata: Title, URL, source, ticker, published date.
        distance: The vector distance (smaller is closer).
    """

    chunk_id: int
    text: str
    metadata: dict[str, Any]
    distance: float


class CorpusStore:
    """The trusted corpus collection."""

    def __init__(
        self,
        cfg: config.RagConfig,
        embeddings: lc_embeddings.Embeddings,
        embed_model: str,
        client: Any = None,
    ) -> None:
        """Connects to the vector store.

        Args:
            cfg: The RAG settings.
            embeddings: The (prefixed) embedding model.
            embed_model: Its alias; stored on the collection so a store
                built with another model is refused.
            client: A Chroma client (tests); None connects over HTTP.
        """
        if client is None:
            client = chromadb.HttpClient(
                host=cfg.chroma_host, port=cfg.chroma_port
            )
        self._client = client
        self._cfg = cfg
        self._embed_model = embed_model
        self._embeddings = embeddings
        self._store: vectorstores.VectorStore | None = None

    def _open(self) -> vectorstores.VectorStore:
        if self._store is None:
            collection = self._client.get_or_create_collection(
                self._cfg.collection,
                metadata={"embed_model": self._embed_model},
                configuration={"hnsw": {"space": "cosine"}},
            )
            built_with = (collection.metadata or {}).get("embed_model")
            if built_with != self._embed_model:
                raise StoreMismatchError(
                    f"collection {self._cfg.collection} was built with "
                    f"{built_with}, not {self._embed_model}: run "
                    "`make -C python reindex`"
                )
            self._store = langchain_chroma.Chroma(
                client=self._client,
                collection_name=self._cfg.collection,
                embedding_function=self._embeddings,
            )
        return self._store

    def reset(self) -> None:
        """Deletes and recreates the collection (reindex)."""
        # It may not exist yet.
        with contextlib.suppress(Exception):
            self._client.delete_collection(self._cfg.collection)
        self._store = None
        self._open()

    def count(self) -> int:
        """Chunks in the collection."""
        self._open()
        return self._client.get_collection(self._cfg.collection).count()

    async def add(
        self,
        ids: Sequence[int],
        texts: Sequence[str],
        metadatas: Sequence[dict[str, Any]],
    ) -> None:
        """Embeds and adds chunks (replacing any with the same id)."""
        await self._open().aadd_texts(
            list(texts),
            metadatas=[
                {k: v for k, v in m.items() if v is not None} for m in metadatas
            ],
            ids=[str(i) for i in ids],
        )

    async def delete(self, ids: Sequence[int]) -> None:
        """Removes chunks."""
        if ids:
            await self._open().adelete(ids=[str(i) for i in ids])

    async def search(self, query: str, k: int) -> list[Hit]:
        """The ``k`` chunks nearest to ``query``."""
        found = await self._open().asimilarity_search_with_score(query, k=k)
        return [_hit(doc, score) for doc, score in found]


def _hit(doc: lc_documents.Document, distance: float) -> Hit:
    return Hit(
        chunk_id=int(doc.id) if doc.id is not None else -1,
        text=doc.page_content,
        metadata=dict(doc.metadata),
        distance=float(distance),
    )
