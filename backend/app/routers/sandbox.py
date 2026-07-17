"""
Per-project sandbox configuration — SANDBOX-01.
PUT /api/projects/{id}/sandbox-config  — Lead+ sets provider + API key (OPSEC gated)
GET /api/projects/{id}/sandbox-config  — Lead+ reads current config (API key NOT returned)

Note: plan specified backend/app/routers/projects/sandbox.py but creating a
projects/ subpackage would shadow the existing flat-file app/routers/projects.py
(1500+ LOC). Placed here as app/routers/sandbox.py instead — same import path used
in main.py.
"""
from __future__ import annotations
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import encrypt_credentials
from app.database import get_session
from app.models.projects import ProjectRole
from app.models.sandbox import SandboxConfig, SandboxReport as SandboxReportModel
from app.schemas.sandbox import SandboxConfigCreate, SandboxConfigRead, SandboxReportRead
from app.security.project_membership import require_project_membership

log = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/projects",
    tags=["sandbox"],
)

# Public-submission providers: operators must acknowledge OPSEC risk before enabling
_PUBLIC_PROVIDERS = frozenset({"anyrun", "hybridanalysis", "joesandbox", "triage"})


def _validate_sandbox_opsec(provider: str, public_warning_acknowledged: bool) -> None:
    """Raise 422 if a public-submission provider is enabled without OPSEC acknowledgement."""
    if provider in _PUBLIC_PROVIDERS and not public_warning_acknowledged:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "public_warning_acknowledged must be true for free-tier sandbox providers "
                f"({', '.join(sorted(_PUBLIC_PROVIDERS))}). "
                "These providers make submitted samples publicly accessible. "
                "Acknowledge this OPSEC risk in the UI before enabling."
            ),
        )


@router.put("/{project_id}/sandbox-config", response_model=SandboxConfigRead)
async def upsert_sandbox_config(
    project_id: uuid.UUID,
    body: SandboxConfigCreate,
    db: AsyncSession = Depends(get_session),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
) -> SandboxConfigRead:
    _validate_sandbox_opsec(body.provider, body.public_warning_acknowledged)
    # Encrypt API key before storage
    api_key_enc: str | None = None
    if body.api_key:
        api_key_enc = encrypt_credentials(
            settings.SECRET_KEY,
            {"type": "apiKey", "key": body.api_key},
        )
    # Upsert: find existing row for project or create new
    result = await db.execute(
        select(SandboxConfig).where(SandboxConfig.project_id == project_id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.provider = body.provider
        if api_key_enc is not None:
            existing.api_key_enc = api_key_enc
        existing.enabled = body.enabled
        existing.public_warning_acknowledged = body.public_warning_acknowledged
        existing.options = body.options
        row = existing
    else:
        row = SandboxConfig(
            project_id=project_id,
            provider=body.provider,
            api_key_enc=api_key_enc,
            enabled=body.enabled,
            public_warning_acknowledged=body.public_warning_acknowledged,
            options=body.options,
        )
        db.add(row)
    await db.commit()
    await db.refresh(row)
    log.info(
        "sandbox_config_upserted project_id=%s provider=%s enabled=%s",
        project_id, row.provider, row.enabled,
    )
    return SandboxConfigRead.model_validate(row)


@router.get("/{project_id}/sandbox-config", response_model=SandboxConfigRead)
async def get_sandbox_config(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
) -> SandboxConfigRead:
    result = await db.execute(
        select(SandboxConfig).where(SandboxConfig.project_id == project_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No sandbox config for this project")
    return SandboxConfigRead.model_validate(row)


@router.get(
    "/{project_id}/events/{event_id}/sandbox-report",
    response_model=SandboxReportRead,
)
async def get_event_sandbox_report(
    project_id: uuid.UUID,
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
) -> SandboxReportRead:
    """Return the most recent sandbox report for an event, scoped to the project.
    Returns 404 if no report exists for this event.
    """
    result = await db.execute(
        select(SandboxReportModel)
        .where(
            SandboxReportModel.event_id == event_id,
            SandboxReportModel.project_id == project_id,
        )
        .order_by(SandboxReportModel.submitted_at.desc())
        .limit(1)
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="No sandbox report found for this event")
    return SandboxReportRead.model_validate(report)
