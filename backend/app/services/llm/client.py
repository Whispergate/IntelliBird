"""LiteLLM async wrapper — Phase 17 / AI-04.

Public surface:
  resolve_provider(db, project_id) -> (model_str, api_base, api_key)
  call_llm_streaming(model, messages, api_base, api_key, ...) -> AsyncGenerator[str]
  estimate_input_tokens(model, messages) -> int

Security invariants (enforced, not optional):
  - litellm.proxy_server is NEVER imported (C-5).
  - api_key / api_base are ALWAYS per-call kwargs — never set on the module
    attribute litellm.api_key or litellm.api_base (C-4 / credential isolation).
  - Ollama model strings carry the ollama_chat/ prefix (chat completions API),
    never the legacy ollama/ prefix.
  - timeout=120 is always forwarded to acompletion.
"""
from __future__ import annotations

import os
from typing import AsyncGenerator

import litellm  # SDK only — NEVER import litellm.proxy_server (C-5)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt_credentials
from app.models.ai import AIProvider

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT: int = 120
DEFAULT_MAX_TOKENS_SUMMARY: int = 1024
DEFAULT_MAX_TOKENS_DIGEST: int = 2048

# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


async def resolve_provider(
    db: AsyncSession,
    project_id,  # uuid.UUID | str — accept either
) -> tuple[str, str | None, str | None]:
    """Resolve LiteLLM model string, api_base, and api_key for a project.

    Returns:
        (model_str, api_base, api_key)

        model_str carries the LiteLLM provider prefix:
          - "ollama_chat/{model_name}" for Ollama (chat completions)
          - "openai/{model_name}" for OpenAI
          - "anthropic/{model_name}" for Anthropic

        api_base: None for hosted providers; Ollama URL for Ollama.
        api_key: None for Ollama; decrypted key for hosted providers.

    Raises:
        ValueError: No AIProvider row for this project, or unknown provider_type.
    """
    row: AIProvider | None = (
        await db.execute(select(AIProvider).where(AIProvider.project_id == project_id))
    ).scalar_one_or_none()

    if row is None:
        raise ValueError(f"No AI provider configured for project {project_id}")

    if row.provider_type == "ollama":
        model_str = f"ollama_chat/{row.model_name}"
        api_base: str | None = row.api_base or os.environ.get(
            "OLLAMA_BASE_URL", "http://ollama:11434"
        )
        api_key: str | None = None

    elif row.provider_type == "openai":
        model_str = f"openai/{row.model_name}"
        api_base = None
        api_key = (
            decrypt_credentials(os.environ["SECRET_KEY"], row.credentials_enc)
            if row.credentials_enc
            else None
        )

    elif row.provider_type == "anthropic":
        model_str = f"anthropic/{row.model_name}"
        api_base = None
        api_key = (
            decrypt_credentials(os.environ["SECRET_KEY"], row.credentials_enc)
            if row.credentials_enc
            else None
        )

    else:
        raise ValueError(f"Unknown provider_type {row.provider_type!r}")

    return model_str, api_base, api_key


# ---------------------------------------------------------------------------
# Streaming call
# ---------------------------------------------------------------------------


async def call_llm_streaming(
    model: str,
    messages: list[dict],
    api_base: str | None,
    api_key: str | None,
    max_tokens: int = DEFAULT_MAX_TOKENS_SUMMARY,
    timeout: int = DEFAULT_TIMEOUT,
) -> AsyncGenerator[str, None]:
    """Async generator that yields token strings from a streaming LLM call.

    Per-call credentials only — litellm.api_key is NEVER mutated here.
    timeout is always forwarded (default 120s) to prevent hung calls.
    """
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": max_tokens,
        "timeout": timeout,
    }
    if api_base is not None:
        kwargs["api_base"] = api_base
    if api_key is not None:
        kwargs["api_key"] = api_key

    response = await litellm.acompletion(**kwargs)
    async for chunk in response:
        content: str = chunk.choices[0].delta.content or ""
        if content:
            yield content


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def estimate_input_tokens(model: str, messages: list[dict]) -> int:
    """Estimate input token count using litellm.token_counter (sync).

    Falls back to a rough chars/4 heuristic when the model is unrecognised
    or token_counter raises.  A 20% safety buffer should be applied by the
    caller when using this estimate for budget pre-flight checks.
    """
    try:
        return int(litellm.token_counter(model=model, messages=messages))
    except Exception:
        return sum(len(m.get("content", "")) for m in messages) // 4
