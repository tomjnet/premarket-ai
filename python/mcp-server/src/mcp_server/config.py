"""MCP server settings, read once from the environment.

A missing or weak secret stops the server at startup.
"""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses
import pathlib

from psycopg import conninfo

_MIN_SECRET_CHARS = 32
# nomic-embed-text (gpu4gb, cpu) is trained with task prefixes; bge-m3 not.
_QUERY_PREFIX = {
    "gpu4gb": "search_query: ",
    "cpu": "search_query: ",
    "gpu8gb": "",
    "gpu16gb": "",
}


class ConfigError(ValueError):
    """A setting is missing or invalid."""


def _require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set")
    return value


def _secret(env: Mapping[str, str], name: str) -> str:
    value = _require(env, name)
    if len(value) < _MIN_SECRET_CHARS:
        raise ConfigError(
            f"{name} must be a random value of at least {_MIN_SECRET_CHARS} "
            "characters (make -C python env generates one)"
        )
    return value


def _int(env: Mapping[str, str], name: str, default: int) -> int:
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


@dataclasses.dataclass(frozen=True)
class Settings:
    """What the tools connect to.

    Attributes:
        token: The service token clients send as ``Bearer``
            (MCP_SERVICE_TOKEN).
        db_host: PGHOST.
        db_port: PGPORT.
        db_name: PGDATABASE.
        db_user: MCP_DB_USER, a read-only role.
        db_password: MCP_DB_PASSWORD.
        redis_host: REDIS_HOST (the tool cache and rate limits).
        redis_password: REDIS_PASSWORD.
        gateway_url: LLM_GATEWAY_URL (embeddings for ``search_news``).
        gateway_key: LLM_GATEWAY_KEY.
        embed_model: EMBED_MODEL, default ``embed-<HW_PROFILE>``.
        query_prefix: The embedding model's query prefix.
        chroma_host: CHROMA_HOST.
        chroma_port: CHROMA_PORT.
        collection: The trusted corpus collection.
        searxng_url: SEARXNG_URL, the web search engine.
        allowed_hosts: Host headers the server answers (DNS rebinding).
        web_per_minute: WEB_SEARCH_PER_MIN, searches per minute.
        prices_per_minute: PRICES_PER_MIN, price lookups per minute.
        fetch_max_bytes: FETCH_MAX_BYTES, the largest page fetched.
        config_dir: Folder with ``universe.yaml`` (PREMARKET_CONFIG_DIR).
    """

    token: str = dataclasses.field(repr=False)
    db_host: str = "postgres"
    db_port: int = 5432
    db_name: str = "premarket"
    db_user: str = "premarket_mcp"
    db_password: str = dataclasses.field(default="", repr=False)
    redis_host: str = "redis"
    redis_password: str = dataclasses.field(default="", repr=False)
    gateway_url: str = "http://llm-gateway:4000/v1"
    gateway_key: str = dataclasses.field(default="", repr=False)
    embed_model: str = "embed-gpu4gb"
    query_prefix: str = "search_query: "
    chroma_host: str = "chroma"
    chroma_port: int = 8000
    collection: str = "trusted_corpus"
    searxng_url: str = "http://searxng:8080"
    allowed_hosts: tuple[str, ...] = ("mcp-server:8000",)
    web_per_minute: int = 30
    prices_per_minute: int = 30
    fetch_max_bytes: int = 1_000_000
    config_dir: pathlib.Path = pathlib.Path("/app/config")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        """Builds the settings from environment variables.

        Args:
            env: The environment.

        Returns:
            The validated settings.

        Raises:
            ConfigError: A setting is missing or invalid.
        """
        profile = env.get("HW_PROFILE", "gpu4gb").strip().lower()
        profile = profile.removesuffix("+")
        hosts = tuple(
            h.strip()
            for h in env.get(
                "MCP_ALLOWED_HOSTS",
                "mcp-server:8000,localhost:*,127.0.0.1:*",
            ).split(",")
            if h.strip()
        )
        return cls(
            token=_secret(env, "MCP_SERVICE_TOKEN"),
            db_host=env.get("PGHOST", "postgres"),
            db_port=_int(env, "PGPORT", 5432),
            db_name=env.get("PGDATABASE", "premarket"),
            db_user=env.get("MCP_DB_USER", "premarket_mcp").strip(),
            db_password=_secret(env, "MCP_DB_PASSWORD"),
            redis_host=env.get("REDIS_HOST", "redis"),
            redis_password=_secret(env, "REDIS_PASSWORD"),
            gateway_url=env.get(
                "LLM_GATEWAY_URL", "http://llm-gateway:4000/v1"
            ).rstrip("/"),
            gateway_key=env.get("LLM_GATEWAY_KEY", "").strip(),
            embed_model=env.get("EMBED_MODEL", "").strip()
            or f"embed-{profile}",
            query_prefix=_QUERY_PREFIX.get(profile, ""),
            chroma_host=env.get("CHROMA_HOST", "chroma"),
            chroma_port=_int(env, "CHROMA_PORT", 8000),
            searxng_url=env.get("SEARXNG_URL", "http://searxng:8080").rstrip(
                "/"
            ),
            allowed_hosts=hosts,
            web_per_minute=_int(env, "WEB_SEARCH_PER_MIN", 30),
            prices_per_minute=_int(env, "PRICES_PER_MIN", 30),
            fetch_max_bytes=_int(env, "FETCH_MAX_BYTES", 1_000_000),
            config_dir=pathlib.Path(
                env.get("PREMARKET_CONFIG_DIR", "/app/config")
            ),
        )

    def dsn(self) -> str:
        """The read-only role's connection string."""
        return conninfo.make_conninfo(
            host=self.db_host,
            port=self.db_port,
            dbname=self.db_name,
            user=self.db_user,
            password=self.db_password,
            application_name="mcp-server",
            options="-c statement_timeout=5000"
            " -c default_transaction_read_only=on",
        )
