"""LangChain models behind the gateway: one factory for chat and embeddings.

The gateway speaks the OpenAI API, so every model is a LangChain OpenAI
model pointed at it; switching Ollama for OpenAI, Claude or Gemini is a
change of alias in the gateway config, not of code.
"""

from __future__ import annotations

from langchain import chat_models
from langchain_core import embeddings as lc_embeddings
from langchain_core import language_models
import langchain_openai

from ai_api.llm import config


def chat_model(
    cfg: config.LlmConfig,
    model: str | None = None,
    max_tokens: int | None = None,
    response_headers: bool = False,
) -> language_models.BaseChatModel:
    """A chat model through the gateway (temperature 0).

    Args:
        cfg: The LLM settings.
        model: A gateway alias; None means the main model.
        max_tokens: Longest answer, or None for the model's default.
        response_headers: Put the gateway's response headers (the call's
            cost) in each answer's ``response_metadata``.

    Returns:
        The model.
    """
    if model is None:
        model = cfg.main_model
    return chat_models.init_chat_model(
        model,
        model_provider="openai",
        base_url=cfg.gateway_url,
        api_key=cfg.api_key,
        temperature=0,
        timeout=cfg.timeout_s,
        max_retries=1,
        max_tokens=max_tokens,
        include_response_headers=response_headers,
    )


def embeddings(cfg: config.LlmConfig) -> lc_embeddings.Embeddings:
    """The embedding model through the gateway.

    Texts are sent as strings: the OpenAI client would otherwise turn them
    into tiktoken ids, which Ollama's models can't read.

    Args:
        cfg: The LLM settings.

    Returns:
        The embeddings; callers add the model's task prefix themselves.
    """
    return langchain_openai.OpenAIEmbeddings(
        model=cfg.embed_model,
        base_url=cfg.gateway_url,
        api_key=cfg.api_key,
        check_embedding_ctx_length=False,
        tiktoken_enabled=False,
        chunk_size=64,
        request_timeout=cfg.timeout_s,
        max_retries=1,
    )
