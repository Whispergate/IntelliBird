"""LLM service package — AI-04, AI-05, AI-06.

Public re-exports for convenience.  Callers may import directly from
sub-modules or from this package.

Example:
    from app.services.llm import resolve_provider, call_llm_streaming
    from app.services.llm import build_summary_messages, EVENT_SUMMARY_PROMPT_V1
    from app.services.llm import check_and_reserve_budget, BUDGET_LUA
    from app.services.llm import probe_ollama, get_ollama_health
"""
from app.services.llm.client import (
    DEFAULT_MAX_TOKENS_DIGEST,
    DEFAULT_MAX_TOKENS_SUMMARY,
    DEFAULT_TIMEOUT,
    call_llm_streaming,
    estimate_input_tokens,
    resolve_provider,
)
from app.services.llm.health import HealthStatus, get_ollama_health, probe_ollama
from app.services.llm.prompts import (
    DIGEST_PROMPT_V1,
    EVENT_SUMMARY_PROMPT_V1,
    META_SUMMARY_PROMPT_V1,
    SUGGESTION_EXTRACTION_PROMPT_V1,
    SYSTEM_PROMPT_DIGEST_V1,
    SYSTEM_PROMPT_META_V1,
    SYSTEM_PROMPT_SUGGESTIONS_V1,
    SYSTEM_PROMPT_V1,
    build_digest_messages,
    build_meta_messages,
    build_suggestion_messages,
    build_summary_messages,
)
from app.services.llm.token_budget import (
    BUDGET_LUA,
    BUDGET_TTL_SECONDS,
    budget_key,
    check_and_reserve_budget,
    record_actual_tokens,
    seconds_until_utc_midnight,
)

__all__ = [
    # client
    "resolve_provider",
    "call_llm_streaming",
    "estimate_input_tokens",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_TOKENS_SUMMARY",
    "DEFAULT_MAX_TOKENS_DIGEST",
    # prompts
    "SYSTEM_PROMPT_V1",
    "SYSTEM_PROMPT_DIGEST_V1",
    "SYSTEM_PROMPT_META_V1",
    "SYSTEM_PROMPT_SUGGESTIONS_V1",
    "EVENT_SUMMARY_PROMPT_V1",
    "DIGEST_PROMPT_V1",
    "META_SUMMARY_PROMPT_V1",
    "SUGGESTION_EXTRACTION_PROMPT_V1",
    "build_summary_messages",
    "build_digest_messages",
    "build_meta_messages",
    "build_suggestion_messages",
    # token_budget
    "BUDGET_LUA",
    "BUDGET_TTL_SECONDS",
    "budget_key",
    "check_and_reserve_budget",
    "record_actual_tokens",
    "seconds_until_utc_midnight",
    # health
    "HealthStatus",
    "probe_ollama",
    "get_ollama_health",
]
