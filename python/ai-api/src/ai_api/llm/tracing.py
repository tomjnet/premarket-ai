"""Langfuse traces of every LLM call (optional, ``observability`` profile).

With LANGFUSE_TRACING=true and the project keys set, every LangChain call
made with ``Tracer.config(...)`` is traced, tagged with the run, the item
and the prompt version. Without them, tracing is off and costs nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core import runnables

_log = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class TracingConfig:
    """Langfuse settings.

    Attributes:
        enabled: LANGFUSE_TRACING.
        host: LANGFUSE_HOST, for example ``http://langfuse-web:3000``.
        public_key: LANGFUSE_PUBLIC_KEY.
        secret_key: LANGFUSE_SECRET_KEY.
    """

    enabled: bool = False
    host: str = ""
    public_key: str = ""
    secret_key: str = dataclasses.field(default="", repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> TracingConfig:
        """Reads the LANGFUSE_* variables; incomplete settings mean off."""
        enabled = env.get("LANGFUSE_TRACING", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        host = env.get("LANGFUSE_HOST", "").strip()
        public_key = env.get("LANGFUSE_PUBLIC_KEY", "").strip()
        secret_key = env.get("LANGFUSE_SECRET_KEY", "").strip()
        complete = bool(host and public_key and secret_key)
        if enabled and not complete:
            _log.warning(
                "LANGFUSE_TRACING is on but LANGFUSE_HOST or the keys are "
                "missing: tracing is off"
            )
        return cls(enabled and complete, host, public_key, secret_key)


class Tracer:
    """Builds LangChain run configs, with Langfuse callbacks when enabled."""

    def __init__(self, cfg: TracingConfig) -> None:
        """Starts the Langfuse client when tracing is enabled."""
        self._cfg = cfg
        self._client = None
        if cfg.enabled:
            import langfuse  # noqa: PLC0415 - only loaded when tracing.

            self._client = langfuse.Langfuse(
                public_key=cfg.public_key,
                secret_key=cfg.secret_key,
                host=cfg.host,
            )
            _log.info("Langfuse tracing to %s", cfg.host)

    @property
    def enabled(self) -> bool:
        """True when calls are traced."""
        return self._client is not None

    def config(
        self,
        name: str,
        tags: list[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> runnables.RunnableConfig:
        """The config for one LangChain call.

        Args:
            name: The run name shown in the trace.
            tags: Trace tags (for example the prompt version).
            metadata: Extra fields (run id, news id, model).

        Returns:
            A ``RunnableConfig`` with the Langfuse handler when enabled.
        """
        tags = [] if tags is None else list(tags)
        meta = {} if metadata is None else dict(metadata)
        meta["langfuse_tags"] = tags
        callbacks = []
        if self._client is not None:
            from langfuse import langchain as lf_langchain  # noqa: PLC0415

            callbacks.append(
                lf_langchain.CallbackHandler(public_key=self._cfg.public_key)
            )
        # A plain dict: RunnableConfig is a TypedDict, and importing
        # LangChain here would slow down every command that reads settings.
        return {
            "run_name": name,
            "tags": tags,
            "metadata": meta,
            "callbacks": callbacks,
        }

    def flush(self) -> None:
        """Sends the buffered traces (end of a batch run)."""
        if self._client is not None:
            self._client.flush()
