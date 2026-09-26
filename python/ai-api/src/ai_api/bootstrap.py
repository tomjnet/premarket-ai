"""``ai-api init``: migrations, the API's database role and demo users.

Runs once per ``up`` as the database owner, in its own short-lived
container. The long-running API then connects as a role that can only read
the legacy tables and users and append audit rows.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
import pathlib

from alembic import command
from alembic import config as alembic_config
import psycopg
from psycopg import sql
import sqlalchemy

from ai_api import config
from ai_api import passwords

_log = logging.getLogger(__name__)

DEMO_USERS = (
    ("trader1", "TRADER"),
    ("analyst1", "ANALYST"),
    ("admin1", "ADMIN"),
)
_MIGRATIONS = pathlib.Path(__file__).parent / "migrations"


def migrate(owner: config.Database) -> None:
    """Applies every Alembic migration (``ai`` schema) as the owner.

    Args:
        owner: The database owner's connection parameters.
    """
    url = sqlalchemy.URL.create(
        "postgresql+psycopg",
        username=owner.user,
        password=owner.password,
        host=owner.host,
        port=owner.port,
        database=owner.name,
    )
    engine = sqlalchemy.create_engine(url)
    try:
        with engine.begin() as connection:
            # The version table lives in `ai`, so it must exist first.
            connection.execute(
                sqlalchemy.text("CREATE SCHEMA IF NOT EXISTS ai")
            )
        with engine.connect() as connection:
            cfg = alembic_config.Config()
            cfg.set_main_option("script_location", str(_MIGRATIONS))
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
            connection.commit()
    finally:
        engine.dispose()


def grant_api_role(
    conn: psycopg.Connection, role: str, password: str, database: str
) -> None:
    """Creates or updates the API's login role with least privilege.

    Args:
        conn: An owner connection.
        role: The role name (AI_DB_USER).
        password: Its password (AI_DB_PASSWORD).
        database: The database to allow connecting to.
    """
    ident = sql.Identifier(role)
    exists = conn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
    ).fetchone()
    if exists is None:
        conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(ident))
    conn.execute(
        sql.SQL(
            "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"
            " NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 20 PASSWORD {}"
        ).format(ident, sql.Literal(password))
    )
    statements = (
        "GRANT CONNECT ON DATABASE {db} TO {role}",
        "GRANT USAGE ON SCHEMA legacy TO {role}",
        "GRANT SELECT ON legacy.ingest_run, legacy.vendor_news_raw,"
        " legacy.companies TO {role}",
        "GRANT USAGE ON SCHEMA ai TO {role}",
        "GRANT SELECT ON ai.app_user TO {role}",
        "GRANT INSERT ON ai.audit_log TO {role}",
        "GRANT USAGE ON SEQUENCE ai.audit_log_id_seq TO {role}",
    )
    for statement in statements:
        conn.execute(
            sql.SQL(statement).format(db=sql.Identifier(database), role=ident)
        )


def seed_demo_users(conn: psycopg.Connection, password: str) -> None:
    """Creates the demo users, or resets their role and password.

    Args:
        conn: An owner connection.
        password: The demo password (DEMO_USER_PASSWORD).
    """
    for username, role in DEMO_USERS:
        conn.execute(
            "INSERT INTO ai.app_user (username, role, password_hash)"
            " VALUES (%s, %s, %s)"
            " ON CONFLICT (username) DO UPDATE SET role = EXCLUDED.role,"
            " password_hash = EXCLUDED.password_hash, disabled = false,"
            " updated_at = now()",
            (username, role, passwords.hash_password(password)),
        )


def run(env: Mapping[str, str]) -> None:
    """Runs the whole init: migrations, role and grants, demo users.

    Args:
        env: The environment (PG* owner settings, AI_DB_USER,
            AI_DB_PASSWORD, DEMO_USER_PASSWORD).

    Raises:
        config.ConfigError: A setting is missing or weak.
    """
    owner = config.Database.from_env(env, "PGUSER", "PGPASSWORD")
    api_role = env.get("AI_DB_USER", "premarket_ai").strip()
    api_password = config.ai_db_password(env)
    demo_password = config.demo_password(env)

    migrate(owner)
    _log.info("migrations applied")
    with psycopg.connect(owner.dsn()) as conn:
        grant_api_role(conn, api_role, api_password, owner.name)
        seed_demo_users(conn, demo_password)
    _log.info(
        "role %s granted; demo users: %s",
        api_role,
        ", ".join(name for name, _ in DEMO_USERS),
    )
