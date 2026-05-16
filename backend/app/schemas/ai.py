"""Pydantic v2 schemas for AI surfaces — Phase 17 / AI-01..07, SCR-04.

Exports:
  AISummariseRequest      — body for POST /api/events/{id}/ai/summarise
  AISummariseResponse     — {job_id} returned on 202 acceptance
  AISuggestionRead        — suggestion row for GET /api/events/{id}/ai/suggestions
  AISuggestionBulkRequest — {ids:[...]} for bulk confirm/discard
  AIProviderRead          — GET /api/projects/{id}/ai-provider (no plaintext key)
  AIProviderUpdate        — PUT /api/projects/{id}/ai-provider body
  AIProviderTestResponse  — POST /api/projects/{id}/ai-provider/test result
  AIDigestResponse        — GET /api/projects/{id}/ai/digest latest row
  AIRerankStatus          — GET /api/projects/{id}/ai/rerank/status
  AIHealthResponse        — GET /api/admin/ai-health
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Summarise
# ---------------------------------------------------------------------------


class AISummariseRequest(BaseModel):
    """Optional body for POST /api/events/{id}/ai/summarise.

    All fields are optional — the endpoint can be called with an empty body
    and will use project defaults.
    """

    # Reserved for future per-request overrides (model, temperature, etc.)
    # Kept minimal for M2 — Claude's Discretion (CONTEXT.md).
    pass


class AISummariseResponse(BaseModel):
    """202 Accepted response for POST /api/events/{id}/ai/summarise.

    job_id is a client-generated UUID that identifies the SSE stream at
    GET /api/ai/jobs/{job_id}/stream. The actor uses this id as the Redis
    key prefix (ai:job:{job_id}:chunks, :done, :cancelled).
    """

    job_id: str


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------


class AISuggestionRead(BaseModel):
    """Serialised AISuggestion row for GET /api/events/{id}/ai/suggestions.

    decided_by_user_id and decided_at are only populated for confirmed /
    discarded rows; pending rows have NULL in both.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ai_summary_id: uuid.UUID
    project_id: uuid.UUID
    event_id: uuid.UUID | None
    suggestion_type: Literal["cve", "attack", "actor", "narrative_op"]
    value: str
    status: Literal["pending", "confirmed", "discarded"]
    created_at: datetime
    decided_at: datetime | None
    decided_by_user_id: uuid.UUID | None


class AISuggestionBulkRequest(BaseModel):
    """Body for POST /api/projects/{id}/ai/suggestions/bulk-confirm|bulk-discard.

    ids must be non-empty and all belong to the project in the URL path.
    The router enforces the project scope guard (PROD-01).
    """

    ids: list[uuid.UUID] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# AI Provider
# ---------------------------------------------------------------------------


class AIProviderRead(BaseModel):
    """GET /api/projects/{id}/ai-provider response.

    api_key / credentials_enc are NEVER returned in plaintext.
    api_key_masked is '••••••••' when an api_key is configured, None otherwise.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    provider_type: Literal["ollama", "openai", "anthropic"]
    model_name: str
    api_base: str | None
    api_key_masked: str | None  # '••••••••' or None
    credentials_key_version: int
    ai_rerank_enabled: bool = False
    ai_digest_enabled: bool = False
    ai_auto_summary_enabled: bool = False
    ai_daily_token_cap: int = 100_000
    digest_schedule_cron: str = "0 6 * * *"
    created_at: datetime
    updated_at: datetime


class AIProviderUpdate(BaseModel):
    """PUT /api/projects/{id}/ai-provider request body.

    All fields are optional — supports partial updates.
    If api_key is omitted, existing credentials_enc is preserved.
    If ai_rerank_enabled transitions false→true, the router enqueues
    one-shot ai_rescore_project per CONTEXT.md §AI reranking trigger.
    """

    provider_type: Literal["ollama", "openai", "anthropic"] | None = None
    model_name: str | None = None
    api_base: str | None = None
    # Plaintext api_key — encrypted by router before storage.
    api_key: str | None = None
    ai_rerank_enabled: bool | None = None
    ai_digest_enabled: bool | None = None
    ai_auto_summary_enabled: bool | None = None
    ai_daily_token_cap: int | None = Field(default=None, ge=1000)
    digest_schedule_cron: str | None = None


class AIProviderTestResponse(BaseModel):
    """POST /api/projects/{id}/ai-provider/test response.

    ok=True means the provider responded correctly to a tiny test prompt.
    latency_ms is measured wall-clock from acompletion call to first response.
    error is populated only when ok=False.
    """

    ok: bool
    latency_ms: int
    error: str | None = None


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------


class AIDigestResponse(BaseModel):
    """GET /api/projects/{id}/ai/digest — latest digest row.

    Returns the most recent ai_summaries row with summary_type='digest'
    for the project. 404 when no digest has been generated yet.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    summary_type: Literal["event", "digest"]
    provider_used: str
    model_used: str
    prompt_template_version: str
    summary_text: str
    tokens_used: int
    requires_analyst_review: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# AI rerank status
# ---------------------------------------------------------------------------


class AIRerankStatus(BaseModel):
    """GET /api/projects/{id}/ai/rerank/status.

    Mirrors Phase 15 RescoreStatusResponse shape so the frontend polling
    pattern is identical (last_rerank_at advances = done signal).
    """

    last_rerank_at: datetime | None
    in_progress_count: int
    total_count: int


# ---------------------------------------------------------------------------
# Admin ai-health
# ---------------------------------------------------------------------------


class AIHealthResponse(BaseModel):
    """GET /api/admin/ai-health response.

    ollama_health: current Ollama probe result from app.state.
    providers_configured_count: total ai_providers rows across all projects.
    """

    ollama_health: Literal["healthy", "slow", "down", "unknown"]
    providers_configured_count: int


# ---------------------------------------------------------------------------
# Attack path analysis — Phase 35 / ATK-01..ATK-05
# ---------------------------------------------------------------------------

import re as _re  # noqa: E402


class AttackPathNode(BaseModel):
    """A single MITRE ATT&CK technique node in the reconstructed kill-chain."""

    id: str
    technique_id: str
    tactic: str
    name: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str

    @field_validator("technique_id")
    @classmethod
    def validate_technique_id(cls, v: str) -> str:
        if not _re.match(r"^T\d{4}(\.\d{3})?$", v):
            raise ValueError(f"Invalid ATT&CK technique ID: {v!r}")
        return v


class AttackPathEdge(BaseModel):
    """A directed edge between two attack path nodes."""

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    rationale: str


class AttackPathRequest(BaseModel):
    """POST /{project_id}/attack-path request body."""

    days: int = Field(default=30, ge=1, le=90)


class AttackPathResponse(BaseModel):
    """Reconstructed MITRE ATT&CK kill-chain graph from LLM analysis."""

    nodes: list[AttackPathNode]
    edges: list[AttackPathEdge]
    truncated: bool
    model_used: str
    events_analysed: int
