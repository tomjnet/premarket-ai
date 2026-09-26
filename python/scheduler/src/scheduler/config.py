"""Scheduler settings, read once from the environment."""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses

from ai_api import config as ai_config

RUN_MODES = ("production", "demo")


def _positive(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise ai_config.ConfigError(
            f"{name} must be an integer, got {raw!r}"
        ) from e
    if value <= 0:
        raise ai_config.ConfigError(f"{name} must be positive, got {value}")
    return value


def _money(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as e:
        raise ai_config.ConfigError(f"{name} must be a number") from e
    if value < 0:
        raise ai_config.ConfigError(f"{name} can't be negative")
    return value


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw not in ("true", "false"):
        raise ai_config.ConfigError(f"{name} must be true or false")
    return raw == "true"


@dataclasses.dataclass(frozen=True)
class Settings:
    """What the scheduler runs, and against what.

    Attributes:
        run_mode: RUN_MODE: ``production`` follows the NYSE timeline with
            SLA checks; ``demo`` only runs the nightly retention cleanup
            (``make -C python demo`` runs a whole day at once).
        owner: The database owner (the steps write ``ai.*``).
        redis_host: REDIS_HOST (locks, alerts, the job queue).
        redis_password: REDIS_PASSWORD.
        retention_days: RETENTION_DAYS: AI results kept (90).
        backlog_max: SLA_BACKLOG_MAX: verify jobs still queued at 06:30
            above which the backlog alert fires (50).
        corpus: SCHEDULER_CORPUS: refresh the trusted corpus at 05:00
            (new 8-Ks are the primary sources of the day's verdicts).
        metrics_port: SCHEDULER_METRICS_PORT: Prometheus metrics (9464).
        monthly_budget_usd: LLM_MONTHLY_BUDGET_USD (the budget gauge).
        heartbeat_file: Touched every 30 s; the healthcheck reads it.
    """

    run_mode: str
    owner: ai_config.Database
    redis_host: str
    redis_password: str = dataclasses.field(repr=False)
    retention_days: int = 90
    backlog_max: int = 50
    corpus: bool = True
    metrics_port: int = 9464
    monthly_budget_usd: float = 20.0
    heartbeat_file: str = "/tmp/scheduler.alive"

    @property
    def production(self) -> bool:
        """True in RUN_MODE=production."""
        return self.run_mode == "production"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        """Builds the settings.

        Args:
            env: The environment.

        Returns:
            The validated settings.

        Raises:
            ai_config.ConfigError: A setting is missing or invalid.
        """
        mode = env.get("RUN_MODE", "demo").strip().lower() or "demo"
        if mode not in RUN_MODES:
            raise ai_config.ConfigError(
                f"RUN_MODE must be production or demo, got {mode!r}"
            )
        return cls(
            run_mode=mode,
            owner=ai_config.Database.from_env(env, "PGUSER", "PGPASSWORD"),
            redis_host=env.get("REDIS_HOST", "redis"),
            redis_password=ai_config.redis_password(env),
            retention_days=_positive(env, "RETENTION_DAYS", 90),
            backlog_max=_positive(env, "SLA_BACKLOG_MAX", 50),
            corpus=_flag(env, "SCHEDULER_CORPUS", True),
            metrics_port=_positive(env, "SCHEDULER_METRICS_PORT", 9464),
            monthly_budget_usd=_money(env, "LLM_MONTHLY_BUDGET_USD", 20.0),
        )
