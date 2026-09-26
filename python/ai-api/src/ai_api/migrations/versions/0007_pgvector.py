"""Production (increment 6): the RAG vectors move into Postgres (pgvector).

``ai.chunk`` gains:

- ``embedding vector(768)`` with an HNSW index (cosine), and
  ``embedding_model``: the vector store when ``VECTOR_STORE=pgvector``.
  768 is nomic-embed-text (``gpu4gb`` / ``cpu``); ``make -C python reindex``
  resizes the column for a model of another size (bge-m3: 1024).
- ``tsv``: a generated full-text vector (title weighted above the text)
  with a GIN index, for hybrid retrieval.

The postgres image has had pgvector since increment 0
(``pgvector/pgvector:0.8.0-pg17``); this enables the extension. ChromaDB's
markers (``indexed_at`` / ``embed_model``) stay, so switching back
(``VECTOR_STORE=chroma``) keeps working.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
        ALTER TABLE ai.chunk
          ADD COLUMN embedding vector(768),
          ADD COLUMN embedding_model text,
          ADD COLUMN tsv tsvector GENERATED ALWAYS AS (
            setweight(to_tsvector('english',
                                  coalesce(metadata->>'title', '')), 'A')
            || setweight(to_tsvector('english', text), 'B')
          ) STORED
    """)
    op.execute(
        "CREATE INDEX chunk_embedding_hnsw ON ai.chunk"
        " USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX chunk_tsv_idx ON ai.chunk USING gin (tsv)")
    # The MCP tool search_news filters by company.
    op.execute(
        "CREATE INDEX chunk_ticker_idx ON ai.chunk ((metadata->>'ticker'))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ai.chunk_ticker_idx")
    op.execute("DROP INDEX ai.chunk_tsv_idx")
    op.execute("DROP INDEX IF EXISTS ai.chunk_embedding_hnsw")
    op.execute(
        "ALTER TABLE ai.chunk DROP COLUMN tsv, DROP COLUMN embedding_model,"
        " DROP COLUMN embedding"
    )
