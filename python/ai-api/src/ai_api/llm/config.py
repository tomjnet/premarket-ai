"""LLM settings: the gateway, the hardware profile and the task aliases.

ai-api never names a provider model. It asks the LiteLLM gateway for a task
alias plus the hardware profile, for example ``main-gpu4gb``; the gateway
config (``podman/config/litellm/config.yaml``) pins what that means.
"""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses

PROFILES = ("gpu4gb", "gpu8gb", "gpu16gb", "cpu")
# Embedding size of each profile's embedding model (nomic-embed-text is 768,
# bge-m3 is 1024). The vector indexes are named by it.
_EMBED_DIMS = {"gpu4gb": 768, "gpu8gb": 1024, "gpu16gb": 1024, "cpu": 768}
# nomic-embed-text is trained with task prefixes; bge-m3 uses none.
_NOMIC_PREFIXES = ("search_query: ", "search_document: ", "clustering: ")
_NO_PREFIXES = ("", "", "")
_PREFIXES = {
    "gpu4gb": _NOMIC_PREFIXES,
    "cpu": _NOMIC_PREFIXES,
    "gpu8gb": _NO_PREFIXES,
    "gpu16gb": _NO_PREFIXES,
}
_MIN_KEY_CHARS = 32


class LlmConfigError(ValueError):
    """An LLM setting is missing or invalid."""


def _positive(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as e:
        raise LlmConfigError(f"{name} must be a number, got {raw!r}") from e
    if value <= 0:
        raise LlmConfigError(f"{name} must be positive, got {value}")
    return value


def _alias(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        return default
    return value


@dataclasses.dataclass(frozen=True)
class LlmConfig:
    """Where the gateway is and which aliases to ask it for.

    Attributes:
        gateway_url: The gateway's OpenAI-compatible base URL
            (LLM_GATEWAY_URL).
        api_key: The gateway key (LLM_GATEWAY_KEY).
        hw_profile: The hardware profile (HW_PROFILE): gpu4gb, gpu8gb,
            gpu16gb or cpu.
        main_model: Alias of the main model (LLM_MAIN_MODEL, default
            ``main-<profile>``).
        embed_model: Alias of the embedding model (EMBED_MODEL, default
            ``embed-<profile>``).
        guard_model: Alias of Llama Guard (GUARD_MODEL, default
            ``guard-<profile>``).
        embed_dims: The embedding size (EMBED_DIMS, default by profile).
        timeout_s: Per-call timeout (LLM_TIMEOUT_S).
        concurrency: Calls in flight at once (LLM_CONCURRENCY). Ollama on
            the 4 GB GPU serves two in parallel per model.
        query_prefix: Prefix of a search query to embed.
        document_prefix: Prefix of a document to embed for search.
        cluster_prefix: Prefix of a text to compare with others (L3).
    """

    gateway_url: str
    api_key: str = dataclasses.field(repr=False)
    hw_profile: str = "gpu4gb"
    main_model: str = "main-gpu4gb"
    embed_model: str = "embed-gpu4gb"
    guard_model: str = "guard-gpu4gb"
    embed_dims: int = 768
    timeout_s: float = 300.0
    concurrency: int = 2
    query_prefix: str = _NOMIC_PREFIXES[0]
    document_prefix: str = _NOMIC_PREFIXES[1]
    cluster_prefix: str = _NOMIC_PREFIXES[2]

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> LlmConfig:
        """Reads the LLM settings.

        Args:
            env: The environment.

        Returns:
            The settings.

        Raises:
            LlmConfigError: A setting is missing or invalid.
        """
        profile = env.get("HW_PROFILE", "gpu4gb").strip().lower()
        profile = profile.removesuffix("+")
        if profile not in PROFILES:
            raise LlmConfigError(
                f"HW_PROFILE must be one of {', '.join(PROFILES)}, "
                f"got {profile!r}"
            )
        key = env.get("LLM_GATEWAY_KEY", "").strip()
        if len(key) < _MIN_KEY_CHARS:
            raise LlmConfigError(
                "LLM_GATEWAY_KEY must be a random value of at least "
                f"{_MIN_KEY_CHARS} characters (make -C python env)"
            )
        dims = _positive(env, "EMBED_DIMS", _EMBED_DIMS[profile])
        query, document, cluster = _PREFIXES[profile]
        return cls(
            gateway_url=env.get(
                "LLM_GATEWAY_URL", "http://llm-gateway:4000/v1"
            ).rstrip("/"),
            api_key=key,
            hw_profile=profile,
            main_model=_alias(env, "LLM_MAIN_MODEL", f"main-{profile}"),
            embed_model=_alias(env, "EMBED_MODEL", f"embed-{profile}"),
            guard_model=_alias(env, "GUARD_MODEL", f"guard-{profile}"),
            embed_dims=int(dims),
            timeout_s=_positive(env, "LLM_TIMEOUT_S", 300.0),
            concurrency=int(_positive(env, "LLM_CONCURRENCY", 2)),
            query_prefix=query,
            document_prefix=document,
            cluster_prefix=cluster,
        )
