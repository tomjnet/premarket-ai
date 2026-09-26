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

    def dsn(self) -> str:
        """Returns a libpq connection string (values quoted by psycopg)."""
        return conninfo.make_conninfo(
            host=self.host,
            port=self.port,
            dbname=self.name,
            user=self.user,
            password=self.password,
            application_name="ai-api",
            # No query may hold a connection for long (slow-query DoS).
            options="-c statement_timeout=5000",
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
