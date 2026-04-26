"""Dramatiq AI actors — Phase 17 / AI-06, AI-07, SCR-04.

Three actors all on ``queue_name="ai"`` (isolated from ingest / scoring queues):

  ai_summarise_event  — on-demand event summary with SSE Redis-buffer protocol
  ai_rescore_project  — AI reranking ±15 clamp, writes events.ai_score only
  ai_digest_project   — daily top-10 digest, writes ai_summaries with summary_type='digest'

Per-loop async engine pattern (mandatory — see RESEARCH.md §"Pitfall 2"):
    Each Dramatiq worker thread has its own asyncio event loop.  A module-global
    create_async_engine would bind to the FIRST loop it touches; subsequent calls
    from a different thread raise "Future attached to a different loop".
    Solution: create a fresh engine INSIDE each _async_* helper and await
    engine.dispose() in a finally block — guarantees no connection leak.

SSE Redis protocol owned by this plan:
  ai:job:{job_id}:chunks    List, RPUSHed per token chunk, EX=3600
  ai:job:{job_id}:done      String "1", SET on completion, EX=3600
  ai:job:{job_id}:cancelled String "1", SET by SSE generator on disconnect, EX=300
"""
from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from uuid import UUID

import dramatiq
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SSE Redis key constants
# ---------------------------------------------------------------------------

CHUNKS_TTL: int = 3600  # 1 hour — generous reconnect window
DONE_TTL: int = 3600
CANCELLED_TTL: int = 300  # SSE generator sets this on disconnect

# ---------------------------------------------------------------------------
# Per-loop engine helper
# ---------------------------------------------------------------------------


def _make_engine_and_session():
    """Build a fresh async engine + session factory inside the running loop."""
    from app.config import settings  # noqa: PLC0415 — lazy import
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        future=True,
        pool_size=2,
        max_overflow=2,
    )
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession,
    )
    return engine, session_factory


# ---------------------------------------------------------------------------
# _async_summarise — ai_summarise_event implementation
# ---------------------------------------------------------------------------


async def _async_summarise(job_id: str, event_id: str, project_id: str) -> None:
    """Per-loop async engine implementation for ai_summarise_event."""
    from app.services.redis_client import get_redis  # noqa: PLC0415

    chunks_key = f"ai:job:{job_id}:chunks"
    done_key = f"ai:job:{job_id}:done"
    cancelled_key = f"ai:job:{job_id}:cancelled"

    engine, session_factory = _make_engine_and_session()
    redis = None
    try:
        redis = await get_redis()

        async with session_factory() as db:
            # Lazy imports — avoid hard-requiring env vars at module import time.
            from app.models.events import Event  # noqa: PLC0415
            from app.models.projects import Project  # noqa: PLC0415
            from app.services.llm.client import (  # noqa: PLC0415
                resolve_provider, call_llm_streaming, estimate_input_tokens,
                DEFAULT_MAX_TOKENS_SUMMARY,
            )
            from app.services.llm.token_budget import (  # noqa: PLC0415
                check_and_reserve_budget, record_actual_tokens,
            )
            from app.services.llm.prompts import (  # noqa: PLC0415
                build_summary_messages, build_meta_messages, build_suggestion_messages,
                EVENT_SUMMARY_PROMPT_V1, META_SUMMARY_PROMPT_V1,
                SUGGESTION_EXTRACTION_PROMPT_V1,
            )
            from app.services.llm.suggestion_validator import (  # noqa: PLC0415
                validate_and_stage_suggestions,
            )
            from app.models.ai import AISummary  # noqa: PLC0415

            # 1. Load event + project rows.
            event_uuid = UUID(event_id)
            project_uuid = UUID(project_id)

            event_row: Event | None = (
                await db.execute(select(Event).where(Event.id == event_uuid))
            ).scalar_one_or_none()

            if event_row is None:
                err_payload = json.dumps({"error": f"event {event_id} not found"})
                await redis.rpush(chunks_key, err_payload)
                await redis.expire(chunks_key, CHUNKS_TTL)
                await redis.set(done_key, "1", ex=DONE_TTL)
                return

            project_row: Project | None = (
                await db.execute(select(Project).where(Project.id == project_uuid))
            ).scalar_one_or_none()

            if project_row is None:
                err_payload = json.dumps({"error": f"project {project_id} not found"})
                await redis.rpush(chunks_key, err_payload)
                await redis.expire(chunks_key, CHUNKS_TTL)
                await redis.set(done_key, "1", ex=DONE_TTL)
                return

            # 2. Resolve provider.
            model_str, api_base, api_key = await resolve_provider(db, project_uuid)

            # 3. Build event payload + messages.
            event_payload = {
                "id": str(event_row.id),
                "title": event_row.title,
                "description": event_row.description,
                "stix_type": event_row.stix_type,
                "observed_at": str(event_row.observed_at),
                "tags": event_row.tags or [],
            }
            messages = build_summary_messages(event_payload)

            # 4. Pre-flight token estimation with 20% buffer.
            estimated = estimate_input_tokens(model_str, messages)
            estimated_with_buffer = int(estimated * 1.2)

            # 5. Context window check — hierarchical chunking if > 80%.
            use_chunking = False
            try:
                import litellm  # noqa: PLC0415
                model_info = litellm.get_model_info(model_str)
                context_window = model_info.get("max_input_tokens") or model_info.get(
                    "max_tokens", 4096
                )
                if estimated > context_window * 0.8:
                    use_chunking = True
            except Exception:  # noqa: BLE001
                pass  # Best-effort — proceed without chunking if metadata unavailable

            # 6. Budget pre-flight check.
            cap = project_row.ai_daily_token_cap or 100_000
            allowed, used = await check_and_reserve_budget(
                redis, project_id, estimated_with_buffer, cap
            )
            if not allowed:
                err_payload = json.dumps({
                    "event": "error",
                    "data": "Daily AI token budget exhausted — resets at 00:00 UTC",
                })
                await redis.rpush(chunks_key, err_payload)
                await redis.expire(chunks_key, CHUNKS_TTL)
                await redis.set(done_key, "1", ex=DONE_TTL)
                return

            # 7. Stream (or chunked map-reduce).
            actual_tokens = 0
            summary_text = ""

            if use_chunking:
                # Map-reduce: split description into chunks, summarise each, then meta-summarise.
                raw_content = json.dumps(event_payload, default=str)
                chunk_size = max(500, len(raw_content) // 4)
                content_chunks = [
                    raw_content[i:i + chunk_size]
                    for i in range(0, len(raw_content), chunk_size)
                ]
                partial_summaries: list[str] = []
                for part in content_chunks:
                    part_messages = [messages[0], {"role": "user", "content": part}]
                    part_text = ""
                    async for chunk_text in call_llm_streaming(
                        model_str, part_messages, api_base, api_key,
                        max_tokens=DEFAULT_MAX_TOKENS_SUMMARY,
                    ):
                        part_text += chunk_text
                        actual_tokens += len(chunk_text.split())  # rough count
                    partial_summaries.append(part_text)

                meta_messages = build_meta_messages(partial_summaries)
                async for chunk_text in call_llm_streaming(
                    model_str, meta_messages, api_base, api_key,
                    max_tokens=DEFAULT_MAX_TOKENS_SUMMARY,
                ):
                    # Cancel check between chunks.
                    if await redis.get(cancelled_key):
                        log.info("ai_summarise_event_cancelled job_id=%s", job_id)
                        await record_actual_tokens(redis, project_id, actual_tokens - estimated)
                        await redis.set(done_key, "1", ex=DONE_TTL)
                        return
                    summary_text += chunk_text
                    actual_tokens += len(chunk_text.split())
                    await redis.rpush(chunks_key, chunk_text)
                    await redis.expire(chunks_key, CHUNKS_TTL)

            else:
                # Direct streaming path.
                async for chunk_text in call_llm_streaming(
                    model_str, messages, api_base, api_key,
                    max_tokens=DEFAULT_MAX_TOKENS_SUMMARY,
                ):
                    # Cancel check between chunks (SSE protocol).
                    if await redis.get(cancelled_key):
                        log.info("ai_summarise_event_cancelled job_id=%s", job_id)
                        await record_actual_tokens(redis, project_id, actual_tokens - estimated)
                        await redis.set(done_key, "1", ex=DONE_TTL)
                        return
                    summary_text += chunk_text
                    actual_tokens += len(chunk_text.split())
                    await redis.rpush(chunks_key, chunk_text)
                    await redis.expire(chunks_key, CHUNKS_TTL)

            # 8. Persist AISummary row.
            summary_row = AISummary(
                project_id=project_uuid,
                event_id=event_uuid,
                summary_type="event",
                provider_used=model_str.split("/")[0] if "/" in model_str else model_str,
                model_used=model_str,
                prompt_template_version=EVENT_SUMMARY_PROMPT_V1,
                summary_text=summary_text,
                tokens_used=actual_tokens,
                requires_analyst_review=True,
            )
            db.add(summary_row)
            await db.flush()  # get summary_row.id

            # 9. Suggestion extraction pass (second LLM call, non-streaming).
            try:
                import litellm as _litellm  # noqa: PLC0415
                suggestion_messages = build_suggestion_messages(event_payload)
                sugg_kwargs: dict = {
                    "model": model_str,
                    "messages": suggestion_messages,
                    "stream": False,
                    "max_tokens": 512,
                    "timeout": 60,
                }
                if api_base is not None:
                    sugg_kwargs["api_base"] = api_base
                if api_key is not None:
                    sugg_kwargs["api_key"] = api_key
                sugg_response = await _litellm.acompletion(**sugg_kwargs)
                raw_json = sugg_response.choices[0].message.content or "{}"
                try:
                    extracted = json.loads(raw_json)
                except json.JSONDecodeError:
                    extracted = {}

                candidates: list[tuple[str, str]] = []
                for cve_id in extracted.get("cve_ids", []):
                    candidates.append(("cve", cve_id))
                for tech_id in extracted.get("attack_technique_ids", []):
                    candidates.append(("attack", tech_id))
                for actor_name in extracted.get("actor_names", []):
                    candidates.append(("actor", actor_name))

                if candidates:
                    await validate_and_stage_suggestions(
                        db,
                        ai_summary_id=summary_row.id,
                        project_id=project_uuid,
                        event_id=event_uuid,
                        candidates=candidates,
                    )
            except Exception as sugg_exc:  # noqa: BLE001
                log.warning(
                    "ai_summarise_suggestion_extraction_failed job_id=%s error=%r",
                    job_id, sugg_exc,
                )

            await db.commit()

            # 10. True-up token budget (output tokens are additive).
            await record_actual_tokens(redis, project_id, actual_tokens - estimated)

            # 11. Mark job done.
            await redis.set(done_key, "1", ex=DONE_TTL)
            log.info("ai_summarise_event_complete job_id=%s tokens=%d", job_id, actual_tokens)

    except Exception as exc:
        log.exception("ai_summarise_event_failed job_id=%s error=%r", job_id, exc)
        try:
            if redis is not None:
                err_payload = json.dumps({"event": "error", "data": str(exc)})
                await redis.rpush(chunks_key, err_payload)
                await redis.expire(chunks_key, CHUNKS_TTL)
                await redis.set(done_key, "1", ex=DONE_TTL)
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# _async_rescore — ai_rescore_project implementation
# ---------------------------------------------------------------------------


async def _async_rescore(project_id: str) -> None:
    """Per-loop async engine implementation for ai_rescore_project (SCR-04).

    Clamp rule: ai_score = max(0.0, min(100.0, rule_score + max(-15, min(15, adjustment))))
    Writes to events.ai_score ONLY — never touches events.score.
    """
    from app.services.redis_client import get_redis  # noqa: PLC0415

    project_uuid = UUID(project_id)
    in_progress_key = f"ai:rerank:project:{project_id}:in_progress"

    engine, session_factory = _make_engine_and_session()
    redis = None
    try:
        redis = await get_redis()
        try:
            await redis.set(in_progress_key, "1", ex=1800)
        except Exception as exc:  # noqa: BLE001
            log.warning("ai_rescore_flag_set_failed project_id=%s error=%r", project_id, exc)

        async with session_factory() as db:
            from app.models.events import Event  # noqa: PLC0415
            from app.models.projects import Project  # noqa: PLC0415
            from app.services.llm.client import resolve_provider  # noqa: PLC0415
            import litellm as _litellm  # noqa: PLC0415

            project_row: Project | None = (
                await db.execute(select(Project).where(Project.id == project_uuid))
            ).scalar_one_or_none()

            if project_row is None:
                log.warning("ai_rescore_project_not_found project_id=%s", project_id)
                return

            # Resolve provider.
            model_str, api_base, api_key = await resolve_provider(db, project_uuid)

            # Query events for last 24h, ordered by score DESC.
            rows = (
                await db.execute(
                    select(Event.id, Event.observed_at, Event.score, Event.title, Event.description)
                    .where(
                        Event.project_id == project_uuid,
                        Event.archived.is_(False),
                        text("observed_at > NOW() - INTERVAL '24 hours'"),
                    )
                    .order_by(Event.score.desc().nullslast())
                )
            ).all()

            log.info("ai_rescore_events_fetched project_id=%s count=%d", project_id, len(rows))

            updated_count = 0
            for row in rows:
                event_id, observed_at, rule_score, title, description = row

                if rule_score is None:
                    continue  # Cannot clamp without a base score.

                # Single non-streaming acompletion for reranking.
                try:
                    rerank_messages = [
                        {
                            "role": "system",
                            "content": (
                                "You are a threat intelligence scoring assistant. "
                                "Given an event, suggest a score adjustment in the range "
                                "[-15, +15] relative to the existing rule-computed score. "
                                "Respond with ONLY a JSON object: {\"adjustment\": <number>}. "
                                "No explanation."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps({
                                "title": title,
                                "description": description,
                                "rule_score": float(rule_score),
                            }, default=str),
                        },
                    ]
                    rerank_kwargs: dict = {
                        "model": model_str,
                        "messages": rerank_messages,
                        "stream": False,
                        "max_tokens": 64,
                        "timeout": 30,
                    }
                    if api_base is not None:
                        rerank_kwargs["api_base"] = api_base
                    if api_key is not None:
                        rerank_kwargs["api_key"] = api_key

                    response = await _litellm.acompletion(**rerank_kwargs)
                    raw_text = response.choices[0].message.content or "{}"
                    data = json.loads(raw_text)
                    raw_adjustment = float(data.get("adjustment", 0))
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "ai_rescore_event_llm_failed project_id=%s event_id=%s error=%r",
                        project_id, event_id, exc,
                    )
                    continue

                # ±15 clamp then overall [0, 100] clamp.
                clamped_adjustment = max(-15, min(15, raw_adjustment))
                ai_score_value = max(0.0, min(100.0, float(rule_score) + clamped_adjustment))

                # Write ai_score — UPDATE only (events is a hypertable; most recent
                # 24h rows are uncompressed and support UPDATE).  NEVER touch score.
                try:
                    await db.execute(
                        update(Event)
                        .where(Event.id == event_id, Event.observed_at == observed_at)
                        .values(ai_score=Decimal(str(round(ai_score_value, 2))))
                    )
                    updated_count += 1
                except Exception as upd_exc:  # noqa: BLE001
                    log.warning(
                        "ai_rescore_event_update_failed project_id=%s event_id=%s error=%r",
                        project_id, event_id, upd_exc,
                    )

            await db.commit()
            log.info(
                "ai_rescore_project_complete project_id=%s updated=%d",
                project_id, updated_count,
            )

    finally:
        if redis is not None:
            try:
                await redis.delete(in_progress_key)
            except Exception as exc:  # noqa: BLE001
                log.warning("ai_rerank_flag_clear_failed project_id=%s error=%r", project_id, exc)
        await engine.dispose()


# ---------------------------------------------------------------------------
# _async_digest — ai_digest_project implementation
# ---------------------------------------------------------------------------


async def _async_digest(project_id: str) -> None:
    """Per-loop async engine implementation for ai_digest_project (AI-07).

    Queries top-10 events by COALESCE(ai_score, score) DESC over last 24h.
    Writes an AISummary row with summary_type='digest', event_id=NULL.
    """
    project_uuid = UUID(project_id)
    engine, session_factory = _make_engine_and_session()
    try:
        async with session_factory() as db:
            from app.models.events import Event  # noqa: PLC0415
            from app.models.projects import Project  # noqa: PLC0415
            from app.services.llm.client import (  # noqa: PLC0415
                resolve_provider, DEFAULT_MAX_TOKENS_DIGEST,
            )
            from app.services.llm.prompts import (  # noqa: PLC0415
                build_digest_messages, DIGEST_PROMPT_V1,
            )
            from app.models.ai import AISummary  # noqa: PLC0415
            import litellm as _litellm  # noqa: PLC0415

            project_row: Project | None = (
                await db.execute(select(Project).where(Project.id == project_uuid))
            ).scalar_one_or_none()

            if project_row is None:
                log.warning("ai_digest_project_not_found project_id=%s", project_id)
                return

            # Window count M — total events in last 24h for project.
            m_result = await db.execute(
                select(Event.id)
                .where(
                    Event.project_id == project_uuid,
                    Event.archived.is_(False),
                    text("observed_at > NOW() - INTERVAL '24 hours'"),
                )
            )
            window_count = len(m_result.all())

            # Top-10 events by COALESCE(ai_score, score) DESC.
            top_rows = (
                await db.execute(
                    select(Event)
                    .where(
                        Event.project_id == project_uuid,
                        Event.archived.is_(False),
                        text("observed_at > NOW() - INTERVAL '24 hours'"),
                    )
                    .order_by(
                        text("COALESCE(ai_score, score) DESC NULLS LAST")
                    )
                    .limit(10)
                )
            ).scalars().all()

            if not top_rows:
                log.info("ai_digest_no_events project_id=%s", project_id)
                return

            # Build digest payload.
            events_payload = [
                {
                    "id": str(e.id),
                    "title": e.title,
                    "description": e.description,
                    "observed_at": str(e.observed_at),
                    "score": float(e.score) if e.score is not None else None,
                    "ai_score": float(e.ai_score) if e.ai_score is not None else None,
                    "tags": e.tags or [],
                }
                for e in top_rows
            ]

            model_str, api_base, api_key = await resolve_provider(db, project_uuid)

            digest_messages = build_digest_messages(events_payload)

            # Non-streaming acompletion — digest is page-only delivery.
            digest_kwargs: dict = {
                "model": model_str,
                "messages": digest_messages,
                "stream": False,
                "max_tokens": DEFAULT_MAX_TOKENS_DIGEST,
                "timeout": 120,
            }
            if api_base is not None:
                digest_kwargs["api_base"] = api_base
            if api_key is not None:
                digest_kwargs["api_key"] = api_key

            response = await _litellm.acompletion(**digest_kwargs)
            summary_text = response.choices[0].message.content or ""
            tokens_used = 0
            try:
                tokens_used = response.usage.total_tokens or 0
            except Exception:  # noqa: BLE001
                pass

            # Persist digest summary row.
            summary_row = AISummary(
                project_id=project_uuid,
                event_id=None,  # digest-level: no specific event
                summary_type="digest",
                provider_used=model_str.split("/")[0] if "/" in model_str else model_str,
                model_used=model_str,
                prompt_template_version=DIGEST_PROMPT_V1,
                summary_text=summary_text,
                tokens_used=tokens_used,
                requires_analyst_review=False,
            )
            db.add(summary_row)
            await db.commit()

            log.info(
                "ai_digest_project_complete project_id=%s top_n=%d window=%d",
                project_id, len(top_rows), window_count,
            )

    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Dramatiq actors
# ---------------------------------------------------------------------------


@dramatiq.actor(queue_name="ai", max_retries=1, min_backoff=5_000, max_backoff=30_000)
def ai_summarise_event(job_id: str, event_id: str, project_id: str) -> None:
    """On-demand event summary actor with SSE Redis-buffer protocol.

    Args:
        job_id:     UUID string for the SSE job (caller-generated).
        event_id:   UUID string of the event to summarise.
        project_id: UUID string of the owning project.

    SSE Redis keys (owned by this actor):
        ai:job:{job_id}:chunks    — RPUSH token chunks here, EX=3600
        ai:job:{job_id}:done      — SET "1" on completion, EX=3600
        ai:job:{job_id}:cancelled — checked between chunk yields; set by SSE on disconnect
    """
    try:
        asyncio.run(_async_summarise(job_id, event_id, project_id))
    except Exception as exc:
        log.exception(
            "ai_summarise_event_actor_failed job_id=%s event_id=%s error=%r",
            job_id, event_id, exc,
        )
        raise


@dramatiq.actor(queue_name="ai", max_retries=1, min_backoff=5_000, max_backoff=30_000)
def ai_rescore_project(project_id: str) -> None:
    """AI reranking pass — clamps adjustment to ±15, writes events.ai_score only.

    Args:
        project_id: UUID string of the project to rerank.
    """
    try:
        asyncio.run(_async_rescore(project_id))
        log.info("ai_rescore_project_complete project_id=%s", project_id)
    except Exception as exc:
        log.exception("ai_rescore_project_failed project_id=%s error=%r", project_id, exc)
        raise


@dramatiq.actor(queue_name="ai", max_retries=1, min_backoff=10_000, max_backoff=60_000)
def ai_digest_project(project_id: str) -> None:
    """Daily digest actor — top-10 events by COALESCE(ai_score, score), writes digest row.

    Args:
        project_id: UUID string of the project to generate a digest for.
    """
    try:
        asyncio.run(_async_digest(project_id))
        log.info("ai_digest_project_complete project_id=%s", project_id)
    except Exception as exc:
        log.exception("ai_digest_project_failed project_id=%s error=%r", project_id, exc)
        raise


# ---------------------------------------------------------------------------
# _async_draft_scenario_narrative — ai_draft_scenario_narrative implementation
# ---------------------------------------------------------------------------


async def _async_draft_scenario_narrative(
    job_id: str,
    scenario_id: str,
    project_id: str,
    user_id: str | None,
) -> None:
    """Per-loop async engine implementation for ai_draft_scenario_narrative (AI-08).

    SSE Redis protocol (mirrors ai_summarise_event):
      ai:job:{job_id}:chunks    — RPUSH token chunks here, EX=600
      ai:job:{job_id}:done      — SET "1" on completion, EX=600
      ai:job:{job_id}:error     — SET reason string on terminal error, EX=600
      ai:job:{job_id}:cancelled — checked between chunk yields; set by SSE on disconnect
    """
    from datetime import datetime, timezone  # noqa: PLC0415

    from app.services.redis_client import get_redis  # noqa: PLC0415

    chunks_key = f"ai:job:{job_id}:chunks"
    done_key = f"ai:job:{job_id}:done"
    cancelled_key = f"ai:job:{job_id}:cancelled"
    error_key = f"ai:job:{job_id}:error"

    NARRATIVE_TTL: int = 600  # 10 minutes — generous SSE reconnect window

    engine, session_factory = _make_engine_and_session()
    redis = None
    try:
        redis = await get_redis()

        async with session_factory() as db:
            from app.models.tiber import (  # noqa: PLC0415
                TiberScenario, TiberActorProfile, TiberReport,
            )
            from app.models.projects import Project  # noqa: PLC0415
            from app.services.llm.client import (  # noqa: PLC0415
                resolve_provider, call_llm_streaming, estimate_input_tokens,
                DEFAULT_MAX_TOKENS_SUMMARY,
            )
            from app.services.llm.token_budget import (  # noqa: PLC0415
                check_and_reserve_budget, record_actual_tokens,
            )
            from app.services.llm.prompts import (  # noqa: PLC0415
                tiber_scenario_narrative_messages, SCENARIO_NARRATIVE_PROMPT_V1,
            )

            # 1. Load scenario + enforce project_id scope boundary (PROD-01).
            scenario = await db.get(TiberScenario, UUID(scenario_id))
            if scenario is None or str(scenario.project_id) != project_id:
                err_msg = json.dumps({"event": "error", "data": "scenario_not_found_or_project_mismatch"})
                await redis.rpush(chunks_key, err_msg)
                await redis.expire(chunks_key, NARRATIVE_TTL)
                await redis.set(error_key, "scenario_not_found_or_project_mismatch", ex=NARRATIVE_TTL)
                await redis.set(done_key, "1", ex=NARRATIVE_TTL)
                return

            # 2. Load related report and actor (actor may be NULL — SET NULL FK).
            report = await db.get(TiberReport, scenario.tiber_report_id)
            actor = (
                await db.get(TiberActorProfile, scenario.actor_id)
                if scenario.actor_id is not None
                else None
            )

            # 3. Resolve LLM provider for this project.
            project_row: Project | None = (
                await db.execute(select(Project).where(Project.id == UUID(project_id)))
            ).scalar_one_or_none()

            model_str, api_base, api_key = await resolve_provider(db, UUID(project_id))

            # 4. Build structural prompt (C-3 compliant — no f-string of raw user content).
            messages = tiber_scenario_narrative_messages(scenario, actor, report)

            # 5. Token budget pre-flight check (Phase 17 / AI-06 token budget gate).
            estimated = estimate_input_tokens(model_str, messages)
            estimated_with_buffer = int(estimated * 1.2)
            cap = getattr(project_row, "ai_daily_token_cap", None) or 100_000
            allowed, _used = await check_and_reserve_budget(
                redis, project_id, estimated_with_buffer, cap
            )
            if not allowed:
                err_msg = json.dumps({
                    "event": "error",
                    "data": "Daily AI token budget exhausted — resets at 00:00 UTC",
                })
                await redis.rpush(chunks_key, err_msg)
                await redis.expire(chunks_key, NARRATIVE_TTL)
                await redis.set(error_key, "budget_exhausted", ex=NARRATIVE_TTL)
                await redis.set(done_key, "1", ex=NARRATIVE_TTL)
                return

            # 6. Stream narrative — push each token chunk to Redis.
            actual_tokens = 0
            full_text_parts: list[str] = []

            async for chunk_text in call_llm_streaming(
                model_str, messages, api_base, api_key,
                max_tokens=DEFAULT_MAX_TOKENS_SUMMARY,
            ):
                # Cancel signal check between chunk yields.
                if await redis.get(cancelled_key):
                    log.info("ai_draft_scenario_narrative_cancelled job_id=%s", job_id)
                    await record_actual_tokens(redis, project_id, actual_tokens - estimated)
                    await redis.set(done_key, "1", ex=NARRATIVE_TTL)
                    return
                full_text_parts.append(chunk_text)
                actual_tokens += len(chunk_text.split())
                await redis.rpush(chunks_key, chunk_text)
                await redis.expire(chunks_key, NARRATIVE_TTL)

            # 7. Persist final narrative text + metadata JSONB to tiber_scenarios row.
            final_text = "".join(full_text_parts)
            metadata = {
                "ai_drafted": True,
                "provider": model_str.split("/")[0] if "/" in model_str else model_str,
                "model": model_str,
                "tokens_used": actual_tokens,
                "drafted_at": datetime.now(timezone.utc).isoformat(),
                "drafted_by_user_id": user_id,
                "prompt_template_version": SCENARIO_NARRATIVE_PROMPT_V1,
            }
            scenario.ai_draft_narrative = final_text
            scenario.ai_draft_metadata = metadata
            await db.commit()

            # 8. True-up token budget.
            await record_actual_tokens(redis, project_id, actual_tokens - estimated)

            # 9. Mark job done.
            await redis.set(done_key, "1", ex=NARRATIVE_TTL)
            log.info(
                "ai_draft_scenario_narrative_complete job_id=%s scenario_id=%s tokens=%d",
                job_id, scenario_id, actual_tokens,
            )

    except Exception as exc:
        log.exception(
            "ai_draft_scenario_narrative_failed job_id=%s scenario_id=%s error=%r",
            job_id, scenario_id, exc,
        )
        try:
            if redis is not None:
                err_msg = json.dumps({"event": "error", "data": str(exc)})
                await redis.rpush(chunks_key, err_msg)
                await redis.expire(chunks_key, NARRATIVE_TTL)
                await redis.set(error_key, str(exc)[:200], ex=NARRATIVE_TTL)
                await redis.set(done_key, "1", ex=NARRATIVE_TTL)
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# ai_draft_scenario_narrative Dramatiq actor (AI-08)
# ---------------------------------------------------------------------------


@dramatiq.actor(queue_name="ai", max_retries=1, min_backoff=10_000, max_backoff=60_000)
def ai_draft_scenario_narrative(
    job_id: str,
    scenario_id: str,
    project_id: str,
    user_id: str | None,
) -> None:
    """AI-drafted TIBER scenario narrative actor (AI-08).

    On-demand narrative generation with SSE Redis-buffer protocol.
    Runs on the existing ``ai`` queue (NOT ``reports``) so that the Phase 17
    token budget tracking (ai:budget:project:{id}:day:{date}) applies.

    Args:
        job_id:      UUID string for the SSE job (caller-generated).
        scenario_id: UUID string of the TiberScenario to draft a narrative for.
        project_id:  UUID string of the owning project (scope + budget boundary).
        user_id:     UUID string of the requesting user, or None.

    SSE Redis keys (owned by this actor):
        ai:job:{job_id}:chunks    — RPUSH token chunks here, EX=600
        ai:job:{job_id}:done      — SET "1" on completion, EX=600
        ai:job:{job_id}:error     — SET reason on terminal error, EX=600
        ai:job:{job_id}:cancelled — checked between chunk yields; set by SSE on disconnect
    """
    try:
        asyncio.run(
            _async_draft_scenario_narrative(job_id, scenario_id, project_id, user_id)
        )
    except Exception as exc:
        log.exception(
            "ai_draft_scenario_narrative_actor_failed job_id=%s scenario_id=%s error=%r",
            job_id, scenario_id, exc,
        )
        raise
