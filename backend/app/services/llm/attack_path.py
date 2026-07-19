"""AI attack path analysis service - ATK-01..ATK-05.

Public surface:
  parse_attack_path_response(text: str) -> AttackPathResponse
  analyse_attack_path(db, project_id, days, user) -> AttackPathResponse
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.events import Event
from app.models.tags import AttackTechniqueTag
from app.schemas.ai import AttackPathResponse
from app.security.jwt import AuthUser
from app.services.events_query import EventsQueryParams, build_events_query
from app.services.llm.client import (
    call_llm_streaming,
    estimate_input_tokens,
    resolve_provider,
)
from app.services.llm.prompts import build_attack_path_messages

log = structlog.get_logger(__name__)

MAX_EVENTS = 10
MAX_TOKENS_RESPONSE = 800


def parse_attack_path_response(text: str) -> AttackPathResponse:
    """Parse LLM output into AttackPathResponse.

    Strips markdown fences if present. Raises ValueError on invalid JSON or schema.
    """
    stripped = text.strip()
    # Remove ```json ... ``` or ``` ... ``` fences
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc
    return AttackPathResponse.model_validate(data)


async def analyse_attack_path(
    db: AsyncSession,
    project_id: uuid.UUID,
    days: int,
    user: AuthUser,
) -> AttackPathResponse:
    """Fetch latest 50 events, build compact payload, call LLM, return structured graph.

    Raises:
        ValueError("No events in window") - zero events in requested window
        ValueError("No AI provider ...") - resolve_provider raises (propagated)
    """
    # 1. Resolve LLM provider (raises ValueError if not configured)
    model_str, api_base, api_key = await resolve_provider(db, project_id)

    # 2. Query latest 50 events in the days window
    now = datetime.now(tz=timezone.utc)
    observed_from = now - timedelta(days=days)
    dashboard_roles: list[str] | None = (
        list(user.dashboard_roles) if user.dashboard_roles else None
    )
    params = EventsQueryParams(
        observed_from=observed_from,
        sort="observed_desc",
    )
    stmt = build_events_query(params, dashboard_roles, project_id=project_id).limit(
        MAX_EVENTS + 1  # +1 to detect truncation
    )
    result = await db.execute(stmt)
    events: list[Event] = list(result.scalars().all())

    if not events:
        raise ValueError("No events in window")

    truncated = len(events) > MAX_EVENTS
    events = events[:MAX_EVENTS]

    # 3. Fetch attack technique IDs per event (single query)
    event_ids = [e.id for e in events]
    tags_result = await db.execute(
        select(AttackTechniqueTag).where(AttackTechniqueTag.event_id.in_(event_ids))
    )
    tags_by_event: dict[uuid.UUID, list[str]] = {}
    for tag in tags_result.scalars():
        tags_by_event.setdefault(tag.event_id, []).append(tag.technique_id)

    # 4. Build compact payload (C-3: via json.dumps, not f-strings)
    compact_events = [
        {
            "title": e.title,
            "description": (e.description or "")[:300],
            "occurred_at": e.observed_at.isoformat() if e.observed_at else None,
            "tags": list(e.tags or []),
            "attack_technique_ids": tags_by_event.get(e.id, []),
        }
        for e in events
    ]
    payload = {
        "events": compact_events,
        "truncated": truncated,
        "project_days_window": days,
    }

    # 5. Call LLM - collect streaming tokens into a single string
    messages = build_attack_path_messages(payload)
    token_estimate = estimate_input_tokens(model_str, messages)
    log.info(
        "attack_path_llm_call",
        project_id=str(project_id),
        events_count=len(events),
        token_estimate=token_estimate,
        model=model_str,
    )

    chunks: list[str] = []
    async for token in call_llm_streaming(
        model_str,
        messages,
        api_base,
        api_key,
        max_tokens=MAX_TOKENS_RESPONSE,
    ):
        chunks.append(token)
    raw = "".join(chunks)

    # 6. Parse and return
    response = parse_attack_path_response(raw)
    # Attach metadata fields
    response.model_used = model_str
    response.events_analysed = len(events)
    response.truncated = truncated
    return response
