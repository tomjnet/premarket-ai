"""ai-api settings, read once from the environment.

A missing or weak secret stops the process at startup instead of running with
an unsafe default.
"""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses
import pathlib

from psycopg import conninfo

from ai_api.dedup import config as dedup_config
from ai_api.llm import config as llm_config
from ai_api.llm import tracing
from ai_api.rag import config as rag_config

# Values from .env.example that must never reach a running service.
_PLACEHOLDERS = frozenset({"change-me", "changeme", "secret"})
_MIN_SECRET_CHARS = 32
_MIN_DEMO_PASSWORD_CHARS = 12


class ConfigError(ValueError):
    """A setting is missing or invalid."""


def _require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set")
    return value


def _secret(env: Mapping[str, str], name: str) -> str:
    value = _require(env, name)
    if value.lower() in _PLACEHOLDERS or len(value) < _MIN_SECRET_CHARS:
        raise ConfigError(
            f"{name} must be a random value of at least {_MIN_SECRET_CHARS} "
            "characters (make -C python env generates one)"
        )
    return value


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from e
    if value <= 0:
        raise ConfigError(f"{name} must be positive, got {value}")
    return value


def _bool(env: Mapping[str, str], name: str) -> bool:
    raw = env.get(name, "").strip().lower()
    if raw in ("", "0", "false", "no"):
        return False
    if raw in ("1", "true", "yes"):
        return True
    raise ConfigError(f"{name} must be true or false, got {raw!r}")


@dataclasses.dataclass(frozen=True)
class Database:
    """Where and as whom to connect to PostgreSQL.

    Attributes:
        host: Server host.
        port: Server port.
        name: Database name.
        user: Role name.
        password: Role password.
    """

    host: str
    port: int
    name: str
    user: str
    password: str = dataclasses.field(repr=False)

    @classmethod
    def from_env(
        cls, env: Mapping[str, str], user_var: str, password_var: str
    ) -> Database:
        """Reads PGHOST/PGPORT/PGDATABASE plus the given role variables.

        Args:
            env: The environment.
            user_var: The variable holding the role name.
            password_var: The variable holding the role's password.

        Returns:
            The connection parameters.

        Raises:
            ConfigError: A variable is missing.
        """
        return cls(
            host=env.get("PGHOST", "postgres"),
            port=_positive_int(env, "PGPORT", 5432),
            name=env.get("PGDATABASE", "premarket"),
            user=_require(env, user_var),
            password=_require(env, password_var),
        )

    def dsn(
        self, search_path: str | None = None, application: str = "ai-api"
    ) -> str:
        """Returns a libpq connection string (values quoted by psycopg).

        Args:
            search_path: A schema to use for unqualified names (the
                LangGraph checkpointer's tables live in ``graph``).
            application: The ``application_name`` shown in pg_stat_activity.

        Returns:
            The connection string.
        """
        # No query may hold a connection for long (slow-query DoS).
        options = "-c statement_timeout=5000"
        if search_path is not None:
            options += f" -c search_path={search_path}"
        return conninfo.make_conninfo(
            host=self.host,
            port=self.port,
            dbname=self.name,
            user=self.user,
            password=self.password,
            application_name=application,
            options=options,
        )


@dataclasses.dataclass(frozen=True)
class Settings:
    """Runtime settings of the API.

    Attributes:
        database: The API's own least-privilege database role.
        redis_host: Redis host (sessions and login throttling).
        redis_password: Redis password.
        jwt_secret: HMAC key of the access tokens.
        access_token_ttl_s: Access-token lifetime.
        refresh_token_ttl_s: Absolute session lifetime. Refreshing rotates
            the refresh token but never extends the session.
        refresh_grace_s: How long a just-rotated refresh token still returns
            the same new token (two tabs refreshing at once).
        allowed_origins: Browser origins allowed to call the auth endpoints.
        login_max_failures: Failed logins per username before a lockout.
        login_lockout_s: Failure window and lockout length.
        expose_docs: Serve /docs and /openapi.json (off in the stack).
        llm: The gateway settings; None turns "Ask the News" off.
        rag: The vector store and reranker; None turns it off too.
        tracing: Langfuse settings.
        llama_guard: Check chat questions and answers with Llama Guard
            (LLAMA_GUARD, default true).
    """

    database: Database
    redis_host: str
    redis_password: str = dataclasses.field(repr=False)
    jwt_secret: str = dataclasses.field(repr=False, default="")
    access_token_ttl_s: int = 900
    refresh_token_ttl_s: int = 43_200
    refresh_grace_s: int = 30
    allowed_origins: frozenset[str] = frozenset()
    login_max_failures: int = 5
    login_lockout_s: int = 900
    expose_docs: bool = False
    llm: llm_config.LlmConfig | None = None
    rag: rag_config.RagConfig | None = None
    tracing: tracing.TracingConfig = tracing.TracingConfig()
    llama_guard: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        """Builds the settings from environment variables.

        Args:
            env: The environment, usually ``os.environ``.

        Returns:
            The validated settings.

        Raises:
            ConfigError: A setting is missing or invalid.
        """
        origins = frozenset(
            origin.strip().rstrip("/")
            for origin in env.get("ALLOWED_ORIGINS", "").split(",")
            if origin.strip()
        )
        return cls(
            database=Database.from_env(env, "AI_DB_USER", "AI_DB_PASSWORD"),
            redis_host=env.get("REDIS_HOST", "redis"),
            redis_password=_secret(env, "REDIS_PASSWORD"),
            jwt_secret=_secret(env, "JWT_SECRET"),
            access_token_ttl_s=_positive_int(env, "ACCESS_TOKEN_TTL_S", 900),
            refresh_token_ttl_s=_positive_int(
                env, "REFRESH_TOKEN_TTL_S", 43_200
            ),
            refresh_grace_s=_positive_int(env, "REFRESH_GRACE_S", 30),
            allowed_origins=origins,
            login_max_failures=_positive_int(env, "LOGIN_MAX_FAILURES", 5),
            login_lockout_s=_positive_int(env, "LOGIN_LOCKOUT_S", 900),
            expose_docs=_bool(env, "EXPOSE_DOCS"),
            llm=_optional_llm(env),
            rag=_rag(env),
            tracing=tracing.TracingConfig.from_env(env),
            llama_guard=(
                True
                if not env.get("LLAMA_GUARD", "").strip()
                else _bool(env, "LLAMA_GUARD")
            ),
        )


def _optional_llm(env: Mapping[str, str]) -> llm_config.LlmConfig | None:
    """The LLM settings, or None when LLM_GATEWAY_KEY isn't set at all."""
    if not env.get("LLM_GATEWAY_KEY", "").strip():
        return None
    return _llm(env)


def _llm(env: Mapping[str, str]) -> llm_config.LlmConfig:
    try:
        return llm_config.LlmConfig.from_env(env)
    except llm_config.LlmConfigError as e:
        raise ConfigError(str(e)) from e


def _rag(env: Mapping[str, str]) -> rag_config.RagConfig:
    try:
        return rag_config.RagConfig.from_env(env)
    except ValueError as e:
        raise ConfigError(str(e)) from e


def ai_db_password(env: Mapping[str, str]) -> str:
    """Returns the password ``ai-api init`` gives the API's database role.

    Args:
        env: The environment.

    Returns:
        The value of AI_DB_PASSWORD.

    Raises:
        ConfigError: It is missing or weak.
    """
    return _secret(env, "AI_DB_PASSWORD")


def role_password(env: Mapping[str, str], name: str) -> str:
    """Returns a database role's password (``ai-api init`` only).

    Args:
        env: The environment.
        name: The variable, for example WORKER_DB_PASSWORD.

    Returns:
        Its value.

    Raises:
        ConfigError: It is missing or weak.
    """
    return _secret(env, name)


def demo_password(env: Mapping[str, str]) -> str:
    """Returns the demo users' password (``ai-api init`` only).

    Args:
        env: The environment.

    Returns:
        The password from DEMO_USER_PASSWORD.

    Raises:
        ConfigError: It is missing or shorter than 12 characters.
    """
    value = _require(env, "DEMO_USER_PASSWORD")
    if len(value) < _MIN_DEMO_PASSWORD_CHARS:
        raise ConfigError(
            "DEMO_USER_PASSWORD must have at least "
            f"{_MIN_DEMO_PASSWORD_CHARS} characters"
        )
    return value


@dataclasses.dataclass(frozen=True)
class RulesSettings:
    """Settings of ``ai-api rules`` (runs as the database owner).

    Attributes:
        owner: The database owner's connection parameters.
        redis_host: Redis host (dedup index, EDGAR rate limit).
        redis_password: Redis password.
        dedup: Duplicate-check thresholds (DEDUP_*).
        sec_user_agent: SEC_USER_AGENT: a name and contact email. Empty
            means the registry isn't refreshed from SEC.
        registry_max_age_days: Refresh the SEC registry when older.
        stale_max_age_days: Dated text older than this is STALE.
        config_dir: Folder with ``sources.yaml`` (PREMARKET_CONFIG_DIR).
    """

    owner: Database
    redis_host: str
    redis_password: str = dataclasses.field(repr=False)
    dedup: dedup_config.DedupConfig = dedup_config.DedupConfig()
    sec_user_agent: str = ""
    registry_max_age_days: int = 7
    stale_max_age_days: int = 30
    config_dir: pathlib.Path = pathlib.Path("/app/config")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> RulesSettings:
        """Builds the settings from environment variables.

        Args:
            env: The environment.

        Returns:
            The validated settings.

        Raises:
            ConfigError: A setting is missing or invalid.
        """
        try:
            dedup = dedup_config.DedupConfig.from_env(env)
        except ValueError as e:
            raise ConfigError(str(e)) from e
        return cls(
            owner=Database.from_env(env, "PGUSER", "PGPASSWORD"),
            redis_host=env.get("REDIS_HOST", "redis"),
            redis_password=_secret(env, "REDIS_PASSWORD"),
            dedup=dedup,
            sec_user_agent=env.get("SEC_USER_AGENT", "").strip(),
            registry_max_age_days=_positive_int(
                env, "REGISTRY_MAX_AGE_DAYS", 7
            ),
            stale_max_age_days=_positive_int(env, "STALE_MAX_AGE_DAYS", 30),
            config_dir=pathlib.Path(
                env.get("PREMARKET_CONFIG_DIR", "/app/config")
            ),
        )


@dataclasses.dataclass(frozen=True)
class AiSettings:
    """Settings of ``ai-api enrich`` and ``ai-api corpus`` (as the owner).

    Attributes:
        owner: The database owner's connection parameters.
        redis_host: Redis host (L3 vector index).
        redis_password: Redis password.
        dedup: Duplicate-check thresholds (DEDUP_*).
        llm: The gateway settings.
        rag: The vector store and corpus settings.
        tracing: Langfuse settings.
        sec_user_agent: SEC_USER_AGENT (the corpus downloads from SEC).
        config_dir: Folder with ``universe.yaml`` (PREMARKET_CONFIG_DIR).
    """

    owner: Database
    redis_host: str
    redis_password: str = dataclasses.field(repr=False)
    llm: llm_config.LlmConfig
    dedup: dedup_config.DedupConfig = dedup_config.DedupConfig()
    rag: rag_config.RagConfig = rag_config.RagConfig()
    tracing: tracing.TracingConfig = tracing.TracingConfig()
    sec_user_agent: str = ""
    config_dir: pathlib.Path = pathlib.Path("/app/config")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> AiSettings:
        """Builds the settings from environment variables.

        Args:
            env: The environment.

        Returns:
            The validated settings.

        Raises:
            ConfigError: A setting is missing or invalid.
        """
        try:
            dedup = dedup_config.DedupConfig.from_env(env)
        except ValueError as e:
            raise ConfigError(str(e)) from e
        return cls(
            owner=Database.from_env(env, "PGUSER", "PGPASSWORD"),
            redis_host=env.get("REDIS_HOST", "redis"),
            redis_password=_secret(env, "REDIS_PASSWORD"),
            llm=_llm(env),
            dedup=dedup,
            rag=_rag(env),
            tracing=tracing.TracingConfig.from_env(env),
            sec_user_agent=env.get("SEC_USER_AGENT", "").strip(),
            config_dir=pathlib.Path(
                env.get("PREMARKET_CONFIG_DIR", "/app/config")
            ),
        )


def _fraction(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as e:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from e
    if not 0 <= value <= 1:
        raise ConfigError(f"{name} must be between 0 and 1, got {value}")
    return value


def _money(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as e:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from e
    if value < 0:
        raise ConfigError(f"{name} can't be negative, got {value}")
    return value


@dataclasses.dataclass(frozen=True)
class VerifySettings:
    """Settings of the verification worker (``ai-worker``, increment 4).

    Attributes:
        database: The worker's own database role (WORKER_DB_USER /
            WORKER_DB_PASSWORD): it reads items, writes verdicts, evidence
            and review tasks, and the checkpointer's tables.
        redis_host: Redis host (the job queue, run events, cloud budget).
        redis_password: Redis password.
        llm: The gateway settings.
        tracing: Langfuse settings.
        mcp_url: The MCP server's streamable HTTP endpoint (MCP_URL).
        mcp_token: Its service token (MCP_SERVICE_TOKEN).
        hitl_confidence_min: Below this, an item goes to review
            (HITL_CONFIDENCE_MIN, 0.70).
        judge_cloud_model: The escalation alias (JUDGE_CLOUD_MODEL, for
            example ``cloud-openai``); empty keeps every judgement local.
        monthly_budget_usd: The cloud cap (LLM_MONTHLY_BUDGET_USD, $20).
        llama_guard: Run Llama Guard on news (LLAMA_GUARD, default true).
        guard_news_review: An unsafe news item goes to review and skips the
            judge (GUARD_NEWS_REVIEW, default false: evidence only, because
            the 1B guard flags ordinary financial news).
        ml_model_dir: The classic ML models (ML_MODEL_DIR).
        ml_enabled: Run the classic ML baseline (ML_BASELINE, default
            true; it is skipped when torch isn't installed).
        config_dir: Folder with ``universe.yaml`` (PREMARKET_CONFIG_DIR).
    """

    database: Database
    redis_host: str
    redis_password: str = dataclasses.field(repr=False)
    llm: llm_config.LlmConfig
    tracing: tracing.TracingConfig = tracing.TracingConfig()
    mcp_url: str = "http://mcp-server:8000/mcp"
    mcp_token: str = dataclasses.field(default="", repr=False)
    hitl_confidence_min: float = 0.70
    judge_cloud_model: str = ""
    monthly_budget_usd: float = 20.0
    llama_guard: bool = True
    guard_news_review: bool = False
    ml_model_dir: pathlib.Path = pathlib.Path("/models")
    ml_enabled: bool = True
    config_dir: pathlib.Path = pathlib.Path("/app/config")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> VerifySettings:
        """Builds the settings from environment variables.

        Args:
            env: The environment.

        Returns:
            The validated settings.

        Raises:
            ConfigError: A setting is missing or invalid.
        """
        guard = env.get("LLAMA_GUARD", "").strip()
        ml = env.get("ML_BASELINE", "").strip()
        return cls(
            database=Database.from_env(
                env, "WORKER_DB_USER", "WORKER_DB_PASSWORD"
            ),
            redis_host=env.get("REDIS_HOST", "redis"),
            redis_password=_secret(env, "REDIS_PASSWORD"),
            llm=_llm(env),
            tracing=tracing.TracingConfig.from_env(env),
            mcp_url=env.get("MCP_URL", "http://mcp-server:8000/mcp").strip(),
            mcp_token=_secret(env, "MCP_SERVICE_TOKEN"),
            hitl_confidence_min=_fraction(env, "HITL_CONFIDENCE_MIN", 0.70),
            judge_cloud_model=env.get("JUDGE_CLOUD_MODEL", "").strip(),
            monthly_budget_usd=_money(env, "LLM_MONTHLY_BUDGET_USD", 20.0),
            llama_guard=True if not guard else _bool(env, "LLAMA_GUARD"),
            guard_news_review=_bool(env, "GUARD_NEWS_REVIEW"),
            ml_model_dir=pathlib.Path(env.get("ML_MODEL_DIR", "/models")),
            ml_enabled=True if not ml else _bool(env, "ML_BASELINE"),
            config_dir=pathlib.Path(
                env.get("PREMARKET_CONFIG_DIR", "/app/config")
            ),
        )
