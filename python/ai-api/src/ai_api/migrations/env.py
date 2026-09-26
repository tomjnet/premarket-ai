"""Alembic environment: runs on the connection ``ai-api init`` passes in."""

from __future__ import annotations

from alembic import context

_connection = context.config.attributes["connection"]
context.configure(
    connection=_connection,
    version_table_schema="ai",
    transaction_per_migration=True,
)
with context.begin_transaction():
    context.run_migrations()
