"""Users and the audit log (increment 1).

Revision ID: 0001
Revises: none
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ai.app_user (
          username       text PRIMARY KEY
                         CHECK (username ~ '^[a-z][a-z0-9_.-]{0,63}$'),
          role           text NOT NULL
                         CHECK (role IN ('TRADER', 'ANALYST', 'ADMIN')),
          password_hash  text NOT NULL,
          disabled       boolean NOT NULL DEFAULT false,
          created_at     timestamptz NOT NULL DEFAULT now(),
          updated_at     timestamptz NOT NULL DEFAULT now()
        )
    """)
    # Logins, failures, lockouts, token reuse and logouts (90-day retention
    # from increment 6). No passwords or tokens are ever written here.
    op.execute("""
        CREATE TABLE ai.audit_log (
          id         bigserial PRIMARY KEY,
          at         timestamptz NOT NULL DEFAULT now(),
          action     text NOT NULL,
          actor      text,
          client_ip  text,
          detail     jsonb NOT NULL DEFAULT '{}'
        )
    """)
    op.execute("CREATE INDEX audit_log_at_idx ON ai.audit_log (at)")


def downgrade() -> None:
    op.execute("DROP TABLE ai.audit_log")
    op.execute("DROP TABLE ai.app_user")
