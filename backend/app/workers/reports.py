"""Dramatiq reports actors — TIBER-03.

One actor on ``queue_name="reports"`` (isolated from ai / scoring / ingest queues):

  generate_report_actor  — async export engine: MD / PDF / STIX dispatch,
                           BYTEA persistence, monotonic version_number.

Per-loop async engine pattern (mandatory — see RESEARCH.md §"Pitfall 2"):
    Each Dramatiq worker thread has its own asyncio event loop.  A module-global
    create_async_engine would bind to the FIRST loop it touches; subsequent calls
    from a different thread raise "Future attached to a different loop".
    Solution: create a fresh engine INSIDE each _async_* helper and await
    engine.dispose() in a finally block — guarantees no connection leak.

WeasyPrint subprocess isolation (H-5 RSS mitigation):
    This module does NOT load weasyprint — PDF generation is delegated entirely to
    app.services.tiber.exporters.pdf.generate_pdf_bytes which invokes the weasyprint
    CLI via subprocess. C library RSS is reclaimed on subprocess exit.

Filename template: {project_slug}-tiber-{report_slug}-v{N}-{YYYYMMDD}.{ext}
  ext: md / pdf / stix.json
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime, timezone
from uuid import UUID, uuid4

import dramatiq
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

log = logging.getLogger(__name__)

# Extension map — must match report_format_enum values in migration 019.
EXT_MAP: dict[str, str] = {
    "markdown": "md",
    "pdf": "pdf",
    "stix": "stix.json",
}


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
# _async_generate — generate_report_actor implementation
# ---------------------------------------------------------------------------


async def _async_generate(
    tiber_report_id: str,
    project_id: str,
    format_str: str,
    user_id: str | None,
) -> None:
    """Per-loop async engine implementation for generate_report_actor."""
    # Lazy imports — avoid hard-requiring env vars at module import time.
    from app.models.tiber import (  # noqa: PLC0415
        TiberReport, TiberActorProfile, TiberScenario, ReportExport,
    )
    from app.models.projects import Project  # noqa: PLC0415
    from app.services.project_export import slug  # noqa: PLC0415
    from app.services.tiber.exporters.markdown import render_markdown_export  # noqa: PLC0415
    from app.services.tiber.exporters.pdf import generate_pdf_bytes  # noqa: PLC0415
    from app.services.tiber.exporters.stix import (  # noqa: PLC0415
        build_tiber_stix_bundle, validate_stix_bundle_strict,
    )

    engine, session_factory = _make_engine_and_session()
    try:
        async with session_factory() as db:
            # 1. Load report — enforce project_id scope boundary (PROD-01).
            report = await db.get(TiberReport, UUID(tiber_report_id))
            if report is None or str(report.project_id) != project_id:
                raise RuntimeError(
                    f"report_not_found_or_project_mismatch "
                    f"report_id={tiber_report_id} project_id={project_id}"
                )

            # 2. Load actor profiles for this report.
            actors = (
                await db.execute(
                    select(TiberActorProfile).where(
                        TiberActorProfile.tiber_report_id == report.id
                    )
                )
            ).scalars().all()

            # 3. Load scenarios selected for inclusion only.
            scenarios = (
                await db.execute(
                    select(TiberScenario).where(
                        TiberScenario.tiber_report_id == report.id,
                        TiberScenario.selected_for_inclusion.is_(True),
                    )
                )
            ).scalars().all()

            # 4. Format dispatch.
            if format_str == "markdown":
                body_bytes = render_markdown_export(report, list(actors), list(scenarios))

            elif format_str == "pdf":
                # Render Markdown to UTF-8 string → convert to minimal HTML doc
                # → hand to generate_pdf_bytes (subprocess; H-5 truncation applies
                # inside render_markdown_export + the PDF exporter).
                import mistune  # noqa: PLC0415 — subprocess isolation: import lazily
                md_bytes = render_markdown_export(report, list(actors), list(scenarios))
                md_text = md_bytes.decode("utf-8")
                html_body = mistune.create_markdown(escape=True)(md_text)
                html_doc = (
                    "<!doctype html>"
                    "<html><head><meta charset='utf-8'>"
                    f"<title>{report.title}</title>"
                    "</head><body>"
                    f"{html_body}"
                    "</body></html>"
                )
                body_bytes = generate_pdf_bytes(html_doc, timeout=120)

            elif format_str == "stix":
                techniques = sorted(
                    {s.attack_technique_id for s in scenarios if s.attack_technique_id}
                )
                bundle_json = build_tiber_stix_bundle(
                    report, list(actors), list(scenarios), techniques
                )
                validate_stix_bundle_strict(bundle_json)
                body_bytes = bundle_json.encode("utf-8")

            else:
                raise ValueError(f"unsupported_format:{format_str!r}")

            # 5. Compute monotonic version_number (application-layer, not DB constraint).
            next_version_result = await db.execute(
                select(func.coalesce(func.max(ReportExport.version_number), 0) + 1).where(
                    ReportExport.tiber_report_id == report.id,
                    ReportExport.format == format_str,
                )
            )
            next_version = int(next_version_result.scalar_one())

            # 6. Build filename.
            project = await db.get(Project, UUID(project_id))
            proj_slug = slug(project.name) if project else "project"
            rep_slug = slug(report.title)
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            ext = EXT_MAP[format_str]
            filename = f"{proj_slug}-tiber-{rep_slug}-v{next_version}-{date_str}.{ext}"

            # 7. INSERT ReportExport row — snapshot report.state at export time.
            row = ReportExport(
                id=uuid4(),
                tiber_report_id=report.id,
                project_id=report.project_id,
                format=format_str,
                version_number=next_version,
                content_bytea=body_bytes,
                filename=filename,
                generated_by_user_id=UUID(user_id) if user_id else None,
                report_state_at_export=report.state,
            )
            db.add(row)
            await db.commit()

            log.info(
                "report_export_completed report_id=%s format=%s version=%s size_bytes=%s",
                tiber_report_id,
                format_str,
                next_version,
                len(body_bytes),
            )

    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Dramatiq actor
# ---------------------------------------------------------------------------


@dramatiq.actor(queue_name="reports", max_retries=2, min_backoff=10_000, max_backoff=120_000)
def generate_report_actor(
    tiber_report_id: str,
    project_id: str,
    format_str: str,
    user_id: str | None,
) -> None:
    """Async export engine actor.

    Dispatches to MD / PDF / STIX exporter based on format_str.
    Writes BYTEA + filename + monotonic version_number to the reports table.

    Args:
        tiber_report_id: UUID string of the TiberReport to export.
        project_id:      UUID string of the owning project (scope boundary).
        format_str:      One of "markdown", "pdf", "stix".
        user_id:         UUID string of the requesting user, or None.

    Filename: {project_slug}-tiber-{report_slug}-v{N}-{YYYYMMDD}.{ext}
    """
    try:
        asyncio.run(_async_generate(tiber_report_id, project_id, format_str, user_id))
    except subprocess.TimeoutExpired:
        log.exception(
            "generate_report_pdf_timeout report_id=%s",
            tiber_report_id,
        )
        raise
    except subprocess.CalledProcessError:
        log.exception(
            "generate_report_pdf_subprocess_error report_id=%s",
            tiber_report_id,
        )
        raise
    except Exception:
        log.exception(
            "generate_report_failed report_id=%s format=%s",
            tiber_report_id,
            format_str,
        )
        raise
