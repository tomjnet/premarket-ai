"""The RAG vector store, behind LangChain's ``VectorStore`` interface.

``VECTOR_STORE`` picks one of two stores; there is only ever one active:

- ``chroma`` (increments 3 to 5): ``langchain-chroma`` with the thin HTTP
  client, collection ``trusted_corpus``.
- ``pgvector`` (increment 6): the ``ai.chunk.embedding`` column (HNSW,
  cosine) next to the chunk text, through ``ChunkVectors``, a small
  ``VectorStore`` over psycopg. Retrieval is **hybrid** in one SQL
  statement: the vector neighbours and the Postgres full-text matches
  (``ai.chunk.tsv``) fused by reciprocal rank.

Either way the store is only an index: Postgres keeps the chunk text
(``ai.chunk``), and ``make -C python reindex`` rebuilds it. Document ids are
the ``ai.chunk`` ids.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
import contextlib
import dataclasses
from typing import Any, Protocol

import chromadb
import langchain_chroma
from langchain_core import documents as lc_documents
from langchain_core import embeddings as lc_embeddings
from langchain_core import vectorstores
import psycopg
from psycopg import rows

from ai_api.rag import config

# Reciprocal rank fusion: score = sum of 1 / (k + rank) over the two lists.
# 60 is the constant of the original paper (Cormack et al., 2009).
RRF_K = 60
# Each list contributes this many candidates per result asked for.
_CANDIDATES_PER_RESULT = 2
_HNSW_INDEX = "chunk_embedding_hnsw"

Connect = Callable[[], contextlib.AbstractAsyncContextManager[Any]]


class StoreMismatchError(RuntimeError):
    """The store was built with another embedding model or size."""


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
        distance: The cosine distance to the question (smaller is closer).
    """

    chunk_id: int
    text: str
    metadata: dict[str, Any]
    distance: float


class CorpusStore(Protocol):
    """What the corpus indexer and the chat need from a vector store."""

    kind: str

    async def reset(self) -> None:
        """Empties the store (reindex)."""

    async def count(self) -> int:
        """Chunks in the store."""

    async def add(
        self,
        ids: Sequence[int],
        texts: Sequence[str],
        metadatas: Sequence[dict[str, Any]],
    ) -> None:
        """Embeds and adds chunks (replacing any with the same id)."""

    async def delete(self, ids: Sequence[int]) -> None:
        """Removes chunks."""

    async def search(self, query: str, k: int) -> list[Hit]:
        """The ``k`` chunks that best match ``query``."""


def vector_literal(vector: Sequence[float]) -> str:
    """A pgvector text literal: ``[0.1,0.2,...]``."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def _dims_of(type_name: str) -> int | None:
    """768 from ``vector(768)``; None for an untyped column."""
    inside = type_name.partition("(")[2].rstrip(")")
    return int(inside) if inside.isdigit() else None


# The hybrid query. The inner vector query is a plain ORDER BY ... LIMIT so
# the HNSW index serves it. The full-text query ORs the question's words
# (plainto_tsquery ANDs them, which a natural question almost never
# matches); ts_rank_cd ranks chunks with more of them first.
_HYBRID_SQL = """
WITH q AS (
  SELECT replace(plainto_tsquery('english', %(text)s)::text, '&', '|')
         ::tsquery AS query
),
vec AS (
  SELECT id, row_number() OVER (ORDER BY distance) AS rank
  FROM (
    SELECT id, embedding <=> %(vector)s::vector AS distance
    FROM ai.chunk
    WHERE embedding IS NOT NULL
    ORDER BY embedding <=> %(vector)s::vector
    LIMIT %(candidates)s
  ) nearest
),
fts AS (
  SELECT id, row_number() OVER (ORDER BY score DESC, id) AS rank
  FROM (
    SELECT c.id, ts_rank_cd(c.tsv, q.query) AS score
    FROM ai.chunk c, q
    WHERE c.embedding IS NOT NULL AND c.tsv @@ q.query
    ORDER BY score DESC, c.id
    LIMIT %(candidates)s
  ) matched
),
fused AS (
  SELECT id,
         coalesce(1.0 / (%(rrf_k)s + vec.rank), 0)
         + coalesce(1.0 / (%(rrf_k)s + fts.rank), 0) AS score
  FROM vec FULL JOIN fts USING (id)
)
SELECT c.id, c.text, c.metadata,
       c.embedding <=> %(vector)s::vector AS distance, f.score
FROM fused f JOIN ai.chunk c ON c.id = f.id
ORDER BY f.score DESC, distance
LIMIT %(k)s
"""

_VECTOR_SQL = """
SELECT id, text, metadata, embedding <=> %(vector)s::vector AS distance
FROM ai.chunk
WHERE embedding IS NOT NULL
ORDER BY embedding <=> %(vector)s::vector
LIMIT %(k)s
"""


class ChunkVectors(vectorstores.VectorStore):
    """``ai.chunk.embedding`` (pgvector) as a LangChain ``VectorStore``.

    The chunks already exist in ``ai.chunk`` (the corpus writes them), so
    "adding" a text sets its row's embedding, and "deleting" clears it.
    Async only: the API and the indexer are async.
    """

    def __init__(
        self,
        connect: Connect,
        embeddings: lc_embeddings.Embeddings,
        embed_model: str,
    ) -> None:
        """Uses ``connect()`` for every statement.

        Args:
            connect: Returns an async context manager yielding a psycopg
                ``AsyncConnection`` (a pool's ``connection``).
            embeddings: The (prefixed) embedding model.
            embed_model: Its alias, stored with each embedding.
        """
        self._connect = connect
        self._embeddings = embeddings
        self._embed_model = embed_model

    @property
    def embeddings(self) -> lc_embeddings.Embeddings:
        """The embedding model."""
        return self._embeddings

    async def aadd_texts(
        self,
        texts: Iterable[str],
        metadatas: list[dict[str, Any]] | None = None,
        *,
        ids: list[str] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """Embeds ``texts`` and stores the vectors on their chunk rows.

        Args:
            texts: The chunk texts.
            metadatas: Unused: the metadata is already on ``ai.chunk``.
            ids: The ``ai.chunk`` ids, required.
            **kwargs: Unused.

        Returns:
            The ids.

        Raises:
            ValueError: ``ids`` is missing or doesn't match ``texts``.
        """
        del metadatas, kwargs
        texts = list(texts)
        if ids is None or len(ids) != len(texts):
            raise ValueError("ChunkVectors needs one ai.chunk id per text")
        vectors = await self._embeddings.aembed_documents(texts)
        async with self._connect() as conn, conn.cursor() as cur:
            await cur.executemany(
                "UPDATE ai.chunk SET embedding = %s::vector,"
                " embedding_model = %s WHERE id = %s",
                [
                    (vector_literal(v), self._embed_model, int(i))
                    for v, i in zip(vectors, ids, strict=True)
                ],
            )
        return list(ids)

    async def adelete(
        self, ids: list[str] | None = None, **kwargs: Any
    ) -> bool | None:
        """Clears the embeddings of these chunks."""
        del kwargs
        if not ids:
            return None
        async with self._connect() as conn:
            await conn.execute(
                "UPDATE ai.chunk SET embedding = NULL, embedding_model = NULL"
                " WHERE id = ANY (%s)",
                ([int(i) for i in ids],),
            )
        return True

    async def asimilarity_search_with_score(
        self, query: str, k: int = 4, **kwargs: Any
    ) -> list[tuple[lc_documents.Document, float]]:
        """The best chunks for ``query`` with their cosine distances.

        Args:
            query: The question.
            k: How many chunks.
            **kwargs: ``hybrid`` (default True): fuse the full-text
                matches in; False is the vector neighbours only.

        Returns:
            (document, distance) pairs, best first.
        """
        hybrid = bool(kwargs.get("hybrid", True))
        vector = vector_literal(await self._embeddings.aembed_query(query))
        candidates = max(k * _CANDIDATES_PER_RESULT, k)
        params = {
            "vector": vector,
            "text": query,
            "k": k,
            "candidates": candidates,
            "rrf_k": RRF_K,
        }
        async with self._connect() as conn, conn.transaction():
            # The HNSW scan returns at most ef_search rows (default 40).
            await conn.execute(
                f"SET LOCAL hnsw.ef_search = {max(40, candidates)}"
            )
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(_HYBRID_SQL if hybrid else _VECTOR_SQL, params)
            found = await cur.fetchall()
        return [
            (
                lc_documents.Document(
                    id=str(row["id"]),
                    page_content=row["text"],
                    metadata=dict(row["metadata"] or {}),
                ),
                float(row["distance"]),
            )
            for row in found
        ]

    async def asimilarity_search(
        self, query: str, k: int = 4, **kwargs: Any
    ) -> list[lc_documents.Document]:
        """The best chunks for ``query``."""
        found = await self.asimilarity_search_with_score(query, k, **kwargs)
        return [doc for doc, _ in found]

    def similarity_search(
        self, query: str, k: int = 4, **kwargs: Any
    ) -> list[lc_documents.Document]:
        """Not supported: use ``asimilarity_search``."""
        del query, k, kwargs
        raise NotImplementedError("ChunkVectors is async only")

    @classmethod
    def from_texts(
        cls,
        texts: list[str],
        embedding: lc_embeddings.Embeddings,
        metadatas: list[dict[str, Any]] | None = None,
        *,
        ids: list[str] | None = None,
        **kwargs: Any,
    ) -> ChunkVectors:
        """Not supported: the chunks come from ``ai.chunk``."""
        del texts, embedding, metadatas, ids, kwargs
        raise NotImplementedError("ChunkVectors indexes existing ai.chunk rows")


def _hit(doc: lc_documents.Document, distance: float) -> Hit:
    return Hit(
        chunk_id=int(doc.id) if doc.id is not None else -1,
        text=doc.page_content,
        metadata=dict(doc.metadata),
        distance=float(distance),
    )


class ChromaStore:
    """The trusted corpus collection in ChromaDB (increments 3 to 5)."""

    kind = "chroma"

    def __init__(
        self,
        cfg: config.RagConfig,
        embeddings: lc_embeddings.Embeddings,
        embed_model: str,
        client: Any = None,
    ) -> None:
        """Connects to Chroma.

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

    async def reset(self) -> None:
        """Deletes and recreates the collection (reindex)."""
        # It may not exist yet.
        with contextlib.suppress(Exception):
            self._client.delete_collection(self._cfg.collection)
        self._store = None
        self._open()

    async def count(self) -> int:
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


class PgVectorStore:
    """The trusted corpus in ``ai.chunk.embedding`` (increment 6)."""

    kind = "pgvector"

    def __init__(
        self,
        connect: Connect,
        embeddings: lc_embeddings.Embeddings,
        embed_model: str,
        embed_dims: int,
        hybrid: bool = True,
    ) -> None:
        """Uses ``connect()`` for every statement.

        Args:
            connect: Returns an async context manager yielding a psycopg
                ``AsyncConnection``. The API's role only reads; ``add``,
                ``delete`` and ``reset`` need the owner.
            embeddings: The (prefixed) embedding model.
            embed_model: Its alias; chunks embedded with another are
                refused until ``make -C python reindex``.
            embed_dims: Its size: the column's ``vector(n)``.
            hybrid: Fuse full-text matches into the vector search.
        """
        self._connect = connect
        self._vectors = ChunkVectors(connect, embeddings, embed_model)
        self._embed_model = embed_model
        self._embed_dims = embed_dims
        self._hybrid = hybrid
        self._checked = False

    @property
    def vectors(self) -> ChunkVectors:
        """The LangChain ``VectorStore``."""
        return self._vectors

    async def _check(self) -> None:
        if self._checked:
            return
        async with self._connect() as conn:
            cur = conn.cursor(row_factory=rows.tuple_row)
            await cur.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute"
                " WHERE attrelid = 'ai.chunk'::regclass"
                " AND attname = 'embedding' AND NOT attisdropped"
            )
            column = await cur.fetchone()
            if column is None:
                raise StoreMismatchError(
                    "ai.chunk has no embedding column: run `ai-api init`"
                    " (make -C python up)"
                )
            await cur.execute(
                "SELECT DISTINCT embedding_model FROM ai.chunk"
                " WHERE embedding IS NOT NULL LIMIT 2"
            )
            models = [row[0] for row in await cur.fetchall()]
        if _dims_of(column[0]) != self._embed_dims:
            raise StoreMismatchError(
                f"ai.chunk.embedding is {column[0]}, but the embedding model"
                f" has {self._embed_dims} dimensions: run"
                " `make -C python reindex`"
            )
        other = [m for m in models if m != self._embed_model]
        if other:
            raise StoreMismatchError(
                f"ai.chunk was embedded with {other[0]}, not"
                f" {self._embed_model}: run `make -C python reindex`"
            )
        self._checked = True

    async def reset(self) -> None:
        """Clears every embedding and sizes the column for the model."""
        async with self._connect() as conn, conn.transaction():
            await conn.execute(f"DROP INDEX IF EXISTS ai.{_HNSW_INDEX}")
            await conn.execute(
                "UPDATE ai.chunk SET embedding = NULL, embedding_model = NULL"
                " WHERE embedding IS NOT NULL"
            )
            await conn.execute(
                "ALTER TABLE ai.chunk ALTER COLUMN embedding TYPE"
                f" vector({int(self._embed_dims)}) USING NULL"
            )
            await conn.execute(
                f"CREATE INDEX {_HNSW_INDEX} ON ai.chunk"
                " USING hnsw (embedding vector_cosine_ops)"
            )
        self._checked = False

    async def count(self) -> int:
        """Chunks with an embedding."""
        async with self._connect() as conn:
            cur = conn.cursor(row_factory=rows.tuple_row)
            await cur.execute(
                "SELECT count(*) FROM ai.chunk WHERE embedding IS NOT NULL"
            )
            found = await cur.fetchone()
        return int(found[0])

    async def add(
        self,
        ids: Sequence[int],
        texts: Sequence[str],
        metadatas: Sequence[dict[str, Any]],
    ) -> None:
        """Embeds chunks and stores their vectors."""
        del metadatas
        await self._check()
        await self._vectors.aadd_texts(list(texts), ids=[str(i) for i in ids])

    async def delete(self, ids: Sequence[int]) -> None:
        """Clears the vectors of these chunks."""
        await self._vectors.adelete(ids=[str(i) for i in ids])

    async def search(self, query: str, k: int) -> list[Hit]:
        """The ``k`` best chunks: hybrid (vector + full text) by default."""
        await self._check()
        found = await self._vectors.asimilarity_search_with_score(
            query, k=k, hybrid=self._hybrid
        )
        return [_hit(doc, score) for doc, score in found]


def connection_of(conn: psycopg.AsyncConnection) -> Connect:
    """``connect`` for a single connection (the indexer, as the owner)."""

    @contextlib.asynccontextmanager
    async def connect() -> Any:
        yield conn

    return connect


def open_store(
    cfg: config.RagConfig,
    embeddings: lc_embeddings.Embeddings,
    embed_model: str,
    embed_dims: int,
    connect: Connect | None = None,
    store_kind: str | None = None,
) -> CorpusStore:
    """The active vector store (``VECTOR_STORE``).

    Args:
        cfg: The RAG settings.
        embeddings: The (prefixed) embedding model.
        embed_model: Its gateway alias.
        embed_dims: Its size.
        connect: Database connections, for pgvector.
        store_kind: ``chroma`` or ``pgvector``; None is ``cfg.vector_store``.

    Returns:
        The store.

    Raises:
        ValueError: pgvector without ``connect``.
    """
    kind = cfg.vector_store if store_kind is None else store_kind
    if kind == "pgvector":
        if connect is None:
            raise ValueError("the pgvector store needs a database connection")
        return PgVectorStore(
            connect, embeddings, embed_model, embed_dims, hybrid=cfg.hybrid
        )
    return ChromaStore(cfg, embeddings, embed_model)
