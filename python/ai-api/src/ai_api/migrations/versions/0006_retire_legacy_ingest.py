"""Production (increment 6): the C++11 legacy ingester is retired.

The strangler-fig seam switches: ``ai.v_raw_news`` / ``ai.v_ingest_run`` now
read the C++20 ingester's tables (``ingest.*``) instead of ``legacy.*``. The
columns are the same, so nothing that reads the views changes. The AI
results are keyed by (feed date, vendor item id) in ``ai.news_item``, so they
all stay attached to the same items.

The ``ingest`` schema is created by ``sql/03_ingest_schema.sql`` (on a new
database volume) and by the C++20 ingester before every run. A database
that never had it can't switch, so the migration stops with a clear error.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_RAW_COLUMNS = """
    SELECT id, run_id, feed_date, vendor_item_id, headline, body,
           source_url, source_domain, published_at, tickers, synthetic,
           content_hash, is_dup, dup_of, ingested_at
"""
_RUN_COLUMNS = """
    SELECT run_id, feed_date, started_at, finished_at, status,
           rows_received, rows_inserted, dups, workers, error
"""


def _point_views_at(schema: str) -> None:
    op.execute(
        f"CREATE OR REPLACE VIEW ai.v_ingest_run AS {_RUN_COLUMNS}"
        f" FROM {schema}.ingest_run"
    )
    op.execute(
        f"CREATE OR REPLACE VIEW ai.v_raw_news AS {_RAW_COLUMNS}"
        f" FROM {schema}.vendor_news_raw"
    )


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
          IF to_regclass('ingest.vendor_news_raw') IS NULL
             OR to_regclass('ingest.ingest_run') IS NULL THEN
            RAISE EXCEPTION 'schema ingest is missing: run the C++20'
              ' ingester once (make -C python ingest) and init again';
          END IF;
        END
        $$
    """)
    _point_views_at("ingest")


def downgrade() -> None:
    _point_views_at("legacy")
