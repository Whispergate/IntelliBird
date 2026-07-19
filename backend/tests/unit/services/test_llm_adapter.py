"""Unit tests for LiteLLM adapter - AI-04.

Covers:
  - call_llm_streaming yields token strings from streamed acompletion
  - Per-call api_key kwarg used; litellm.api_key module attribute never mutated
  - Ollama providers use ollama_chat/ model prefix
  - timeout=120 always forwarded
  - No f-string with event content in llm service files (code-review gate)
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers - async iterable mock
# ---------------------------------------------------------------------------


def _make_stream_chunks(tokens: list[str]):
    """Build a list of mock acompletion stream chunks."""
    chunks = []
    for token in tokens:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = token
        chunks.append(chunk)
    return chunks


async def _async_iter(items):
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# Test: streaming yields correct strings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acompletion_streaming_yields_chunks() -> None:
    """call_llm_streaming yields each non-empty token string from acompletion."""
    from app.services.llm.client import call_llm_streaming

    tokens = ["Hello", " world", "!"]
    chunks = _make_stream_chunks(tokens)

    # acompletion returns an awaitable that yields chunks when iterated
    mock_response = _async_iter(chunks)

    async def fake_acompletion(**kwargs):
        return mock_response

    with patch("litellm.acompletion", new=fake_acompletion):
        collected = []
        async for token in call_llm_streaming(
            model="ollama_chat/phi3:mini",
            messages=[{"role": "user", "content": "test"}],
            api_base="http://ollama:11434",
            api_key=None,
        ):
            collected.append(token)

    assert collected == tokens


# ---------------------------------------------------------------------------
# Test: per-call api_key; litellm.api_key never mutated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_call_api_key_not_global() -> None:
    """api_key is passed as a per-call kwarg; litellm.api_key stays untouched."""
    import litellm
    from app.services.llm.client import call_llm_streaming

    original_global_key = getattr(litellm, "api_key", None)
    captured_kwargs: dict = {}

    mock_response = _async_iter(_make_stream_chunks(["tok"]))

    async def fake_acompletion(**kwargs):
        captured_kwargs.update(kwargs)
        return mock_response

    secret_key = "sk-test-secret"

    with patch("litellm.acompletion", new=fake_acompletion):
        async for _ in call_llm_streaming(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            api_base=None,
            api_key=secret_key,
        ):
            pass

    # Key must be passed as kwarg, not set globally
    assert captured_kwargs.get("api_key") == secret_key
    assert getattr(litellm, "api_key", None) == original_global_key


# ---------------------------------------------------------------------------
# Test: Ollama provider uses ollama_chat/ prefix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_chat_prefix_used() -> None:
    """resolve_provider returns ollama_chat/ prefix for Ollama providers."""
    from app.services.llm.client import resolve_provider

    uuid.uuid4()
    project_id = uuid.uuid4()

    # Build a minimal mock AIProvider row
    mock_row = MagicMock()
    mock_row.provider_type = "ollama"
    mock_row.model_name = "phi3:mini"
    mock_row.api_base = "http://ollama:11434"

    # Mock the DB session execute → scalar_one_or_none chain
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    model_str, api_base, api_key = await resolve_provider(mock_db, project_id)

    assert model_str == "ollama_chat/phi3:mini"
    assert api_base == "http://ollama:11434"
    assert api_key is None


# ---------------------------------------------------------------------------
# Test: timeout=120 always forwarded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_always_forwarded() -> None:
    """DEFAULT_TIMEOUT=120 is always passed to acompletion kwargs."""
    from app.services.llm.client import DEFAULT_TIMEOUT, call_llm_streaming

    assert DEFAULT_TIMEOUT == 120

    captured_kwargs: dict = {}
    mock_response = _async_iter(_make_stream_chunks(["x"]))

    async def fake_acompletion(**kwargs):
        captured_kwargs.update(kwargs)
        return mock_response

    with patch("litellm.acompletion", new=fake_acompletion):
        async for _ in call_llm_streaming(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            api_base=None,
            api_key=None,
        ):
            pass

    assert captured_kwargs["timeout"] == DEFAULT_TIMEOUT


# ---------------------------------------------------------------------------
# Code-review gate: no f-string with event content in llm service files
# ---------------------------------------------------------------------------


def test_no_f_string_event_content_in_llm_service() -> None:
    """C-3 gate: no f-strings referencing event fields in app/services/llm/.

    Scans all .py files under app/services/llm/ for the pattern  f"...event.
    using grep or a pure-Python scan (falls back if grep unavailable).
    """
    import pathlib
    import re

    llm_dir = pathlib.Path(
        "/home/lavender/Documents/Projects/IntelliBird/backend/app/services/llm"
    )
    assert llm_dir.is_dir(), f"Expected llm dir at {llm_dir}"

    # Pattern: an f-string containing the text 'event.'
    pattern = re.compile(r'f["\'].*event\.')

    violations: list[str] = []
    for py_file in sorted(llm_dir.rglob("*.py")):
        for lineno, line in enumerate(py_file.read_text().splitlines(), 1):
            if pattern.search(line):
                violations.append(f"{py_file.name}:{lineno}: {line.strip()}")

    assert not violations, (
        "C-3 violation: f-string with event content found in app/services/llm/:\n"
        + "\n".join(violations)
    )
