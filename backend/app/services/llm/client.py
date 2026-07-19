"""LiteLLM async wrapper - AI-04.

Public surface:
  resolve_provider(db, project_id) -> (model_str, api_base, api_key)
  call_llm_streaming(model, messages, api_base, api_key, ...) -> AsyncGenerator[str]
  estimate_input_tokens(model, messages) -> int

Security invariants (enforced, not optional):
  - litellm.proxy_server is NEVER imported (C-5).
  - api_key / api_base are ALWAYS per-call kwargs - never set on the module
    attribute litellm.api_key or litellm.api_base (C-4 / credential isolation).
  - Ollama model strings carry the ollama_chat/ prefix (chat completions API),
    never the legacy ollama/ prefix.
  - timeout=120 is always forwarded to acompletion.
"""
from __future__ import annotations

import os
from typing import AsyncGenerator

import litellm  # SDK only - NEVER import litellm.proxy_server (C-5)
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
    project_id,  # uuid.UUID | str - accept either
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

    # Fall back to the global default - the AIProvider row keyed to
    # LEGACY_PROJECT_ID is treated as the system-wide default and is editable
    # via /admin/ai-defaults. Avoid the fallback when project_id IS the legacy
    # sentinel (would loop on its own missing row).
    if row is None:
        from app.models.projects import LEGACY_PROJECT_ID  # noqa: PLC0415
        if str(project_id) != str(LEGACY_PROJECT_ID):
            row = (
                await db.execute(
                    select(AIProvider).where(AIProvider.project_id == LEGACY_PROJECT_ID)
                )
            ).scalar_one_or_none()
        if row is None:
            raise ValueError(f"No AI provider configured for project {project_id}")

    if row.provider_type == "ollama":
        model_str = f"ollama_chat/{_split_models(row.model_name)[0]}"
        # Operator UI accepts arbitrary api_base. In compose, "localhost" /
        # "127.0.0.1" inside a worker container resolves to the worker itself,
        # not the ollama service - silently rewrite to the compose DNS name.
        env_default = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
        api_base: str | None = row.api_base or env_default
        if api_base and ("localhost" in api_base or "127.0.0.1" in api_base):
            api_base = env_default
        api_key: str | None = None

    elif row.provider_type == "openai":
        model_str = f"openai/{_split_models(row.model_name)[0]}"
        api_base = None
        api_key = (
            decrypt_credentials(os.environ["SECRET_KEY"], row.credentials_enc)  # type: ignore[assignment]
            if row.credentials_enc
            else None
        )

    elif row.provider_type == "anthropic":
        model_str = f"anthropic/{_split_models(row.model_name)[0]}"
        api_base = None
        api_key = (
            decrypt_credentials(os.environ["SECRET_KEY"], row.credentials_enc)  # type: ignore[assignment]
            if row.credentials_enc
            else None
        )

    else:
        raise ValueError(f"Unknown provider_type {row.provider_type!r}")

    return model_str, api_base, api_key


def _split_models(raw: str) -> list[str]:
    """Split a comma-separated model_name into a non-empty list of clean names."""
    parts = [m.strip() for m in (raw or "").split(",") if m.strip()]
    return parts or [raw]


async def resolve_provider_models(
    db: AsyncSession,
    project_id,
) -> tuple[list[str], str | None, str | None]:
    """Same as resolve_provider but returns the FULL model list (round-robin pool).

    `model_name` may be comma-separated - e.g. "gemma4:e2b,phi:latest" - to give
    the worker multiple models to rotate across. Each entry is returned with the
    correct LiteLLM provider prefix. Single-model rows return a length-1 list.

    Use with `pick_model(models, counter)` to round-robin per call and with a
    failover loop to skip a model that is timing out.
    """
    row: AIProvider | None = (
        await db.execute(select(AIProvider).where(AIProvider.project_id == project_id))
    ).scalar_one_or_none()
    if row is None:
        from app.models.projects import LEGACY_PROJECT_ID  # noqa: PLC0415
        if str(project_id) != str(LEGACY_PROJECT_ID):
            row = (
                await db.execute(
                    select(AIProvider).where(AIProvider.project_id == LEGACY_PROJECT_ID)
                )
            ).scalar_one_or_none()
        if row is None:
            raise ValueError(f"No AI provider configured for project {project_id}")

    names = _split_models(row.model_name)

    if row.provider_type == "ollama":
        env_default = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
        api_base = row.api_base or env_default
        if api_base and ("localhost" in api_base or "127.0.0.1" in api_base):
            api_base = env_default
        return [f"ollama_chat/{n}" for n in names], api_base, None

    if row.provider_type == "openai":
        api_key = (
            decrypt_credentials(os.environ["SECRET_KEY"], row.credentials_enc)
            if row.credentials_enc
            else None
        )
        return [f"openai/{n}" for n in names], None, api_key  # type: ignore[return-value]

    if row.provider_type == "anthropic":
        api_key = (
            decrypt_credentials(os.environ["SECRET_KEY"], row.credentials_enc)
            if row.credentials_enc
            else None
        )
        return [f"anthropic/{n}" for n in names], None, api_key  # type: ignore[return-value]

    raise ValueError(f"Unknown provider_type {row.provider_type!r}")


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

    Per-call credentials only - litellm.api_key is NEVER mutated here.
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
