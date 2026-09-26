"""``ai-api init``: migrations, the API's database role and demo users.

Runs once per ``up`` as the database owner, in its own short-lived
container. The long-running API then connects as a role that can only read
raw news through the ``ai.v_*`` views, the rule results and the users, and
append audit rows.

Increment 4 adds two more least-privilege roles and the LangGraph
checkpointer's tables (schema ``graph``):

- ``premarket_worker`` (``ai-worker``): reads items and their rule and AI
  results, writes verdicts, evidence and review tasks, and the
  checkpoints;
- ``premarket_mcp`` (``mcp-server``): read-only, the tables its tools
  answer from.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
import pathlib

from alembic import command
from alembic import config as alembic_config
from langgraph.checkpoint import postgres as pg_checkpoint
import psycopg
from psycopg import rows
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


def _login_role(
    conn: psycopg.Connection, role: str, password: str, limit: int
) -> None:
    """Creates or updates a login role without any special privilege."""
    ident = sql.Identifier(role)
    exists = conn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
    ).fetchone()
    if exists is None:
        conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(ident))
    conn.execute(
        sql.SQL(
            "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"
            " NOREPLICATION NOBYPASSRLS CONNECTION LIMIT {} PASSWORD {}"
        ).format(ident, sql.Literal(limit), sql.Literal(password))
    )


def _grant(
    conn: psycopg.Connection,
    role: str,
    database: str,
    statements: tuple[str, ...],
) -> None:
    for statement in statements:
        conn.execute(
            sql.SQL(statement).format(
                db=sql.Identifier(database), role=sql.Identifier(role)
            )
        )


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
    _login_role(conn, role, password, 20)
    # From increment 2 the API reads raw news only through the ai.v_* views
    # (the strangler-fig seam): it has no access to the legacy schema.
    statements = (
        "GRANT CONNECT ON DATABASE {db} TO {role}",
        "REVOKE ALL ON ALL TABLES IN SCHEMA legacy FROM {role}",
        "REVOKE USAGE ON SCHEMA legacy FROM {role}",
        "GRANT USAGE ON SCHEMA ai TO {role}",
        "GRANT SELECT ON ai.app_user TO {role}",
        "GRANT INSERT ON ai.audit_log TO {role}",
        "GRANT USAGE ON SEQUENCE ai.audit_log_id_seq TO {role}",
        "GRANT SELECT ON ai.v_raw_news, ai.v_ingest_run, ai.news_item,"
        " ai.duplicate_link, ai.rule_check, ai.rule_run TO {role}",
        # Increment 3: summaries, extraction and the trusted corpus.
        "GRANT SELECT ON ai.ai_run, ai.news_ai, ai.entity, ai.claim,"
        " ai.document, ai.chunk TO {role}",
        # Increment 4: verdicts, starting runs, deciding reviews (and the
        # learning loop: labeled examples, source reputation).
        "GRANT SELECT ON ai.verify_run, ai.verification, ai.evidence,"
        " ai.review_task, ai.source_reputation TO {role}",
        "GRANT INSERT ON ai.verify_run, ai.eval_example TO {role}",
        "GRANT USAGE ON SEQUENCE ai.verify_run_run_id_seq,"
        " ai.eval_example_id_seq TO {role}",
        "GRANT UPDATE (status, final_verdict, reviewer, comment, decided_at)"
        " ON ai.review_task TO {role}",
        "GRANT UPDATE (reputation, updated_at) ON ai.source_reputation"
        " TO {role}",
    )
    _grant(conn, role, database, statements)


def grant_worker_role(
    conn: psycopg.Connection, role: str, password: str, database: str
) -> None:
    """The verification worker's role (``ai-worker``).

    Args:
        conn: An owner connection.
        role: The role name (WORKER_DB_USER).
        password: Its password (WORKER_DB_PASSWORD).
        database: The database to allow connecting to.
    """
    _login_role(conn, role, password, 40)
    statements = (
        "GRANT CONNECT ON DATABASE {db} TO {role}",
        "REVOKE ALL ON ALL TABLES IN SCHEMA legacy FROM {role}",
        "REVOKE USAGE ON SCHEMA legacy FROM {role}",
        "GRANT USAGE ON SCHEMA ai, graph TO {role}",
        "GRANT SELECT ON ai.v_raw_news, ai.news_item, ai.rule_check,"
        " ai.rule_run, ai.duplicate_link, ai.ai_run, ai.news_ai, ai.entity,"
        " ai.claim, ai.source_reputation TO {role}",
        "GRANT SELECT, UPDATE ON ai.verify_run TO {role}",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ai.verification,"
        " ai.evidence, ai.review_task TO {role}",
        "GRANT USAGE ON SEQUENCE ai.review_task_id_seq TO {role}",
        # The LangGraph checkpointer's tables (created by setup_checkpoints).
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA graph"
        " TO {role}",
    )
    _grant(conn, role, database, statements)


def grant_mcp_role(
    conn: psycopg.Connection, role: str, password: str, database: str
) -> None:
    """The MCP server's read-only role (``mcp-server``).

    Args:
        conn: An owner connection.
        role: The role name (MCP_DB_USER).
        password: Its password (MCP_DB_PASSWORD).
        database: The database to allow connecting to.
    """
    _login_role(conn, role, password, 10)
    statements = (
        "GRANT CONNECT ON DATABASE {db} TO {role}",
        "REVOKE ALL ON ALL TABLES IN SCHEMA legacy FROM {role}",
        "REVOKE USAGE ON SCHEMA legacy FROM {role}",
        "GRANT USAGE ON SCHEMA ai TO {role}",
        "GRANT SELECT ON ai.ticker_registry, ai.source_reputation,"
        " ai.news_item, ai.v_raw_news, ai.verification, ai.evidence"
        " TO {role}",
    )
    _grant(conn, role, database, statements)


def setup_checkpoints(owner: config.Database) -> None:
    """Creates or migrates the LangGraph checkpointer's tables (``graph``).

    Args:
        owner: The database owner's connection parameters.
    """
    with psycopg.connect(
        owner.dsn(search_path="graph"),
        autocommit=True,
        prepare_threshold=0,
        row_factory=rows.dict_row,
    ) as conn:
        pg_checkpoint.PostgresSaver(conn).setup()


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
            AI_DB_PASSWORD, WORKER_DB_USER, WORKER_DB_PASSWORD,
            MCP_DB_USER, MCP_DB_PASSWORD, DEMO_USER_PASSWORD).

    Raises:
        config.ConfigError: A setting is missing or weak.
    """
    owner = config.Database.from_env(env, "PGUSER", "PGPASSWORD")
    api_role = env.get("AI_DB_USER", "premarket_ai").strip()
    api_password = config.ai_db_password(env)
    demo_password = config.demo_password(env)
    roles = [(grant_api_role, api_role, api_password)]
    # Increment 4 roles: granted when their passwords are set.
    for grant, user_var, password_var, default in (
        (
            grant_worker_role,
            "WORKER_DB_USER",
            "WORKER_DB_PASSWORD",
            "premarket_worker",
        ),
        (grant_mcp_role, "MCP_DB_USER", "MCP_DB_PASSWORD", "premarket_mcp"),
    ):
        if env.get(password_var, "").strip():
            name = env.get(user_var, default).strip() or default
            roles.append((grant, name, config.role_password(env, password_var)))

    migrate(owner)
    setup_checkpoints(owner)
    _log.info("migrations applied (ai, graph)")
    with psycopg.connect(owner.dsn()) as conn:
        for grant, role, password in roles:
            grant(conn, role, password, owner.name)
        seed_demo_users(conn, demo_password)
    _log.info(
        "roles %s granted; demo users: %s",
        ", ".join(role for _, role, _ in roles),
        ", ".join(name for name, _ in DEMO_USERS),
    )
