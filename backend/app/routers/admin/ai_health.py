"""GET /api/admin/ai-health - AI-05.

Returns current Ollama health state (set by startup probe) and count of
configured AI providers across all projects.

Auth: Admin role only (via require_admin).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_admin
from app.models.ai import AIProvider
from app.schemas.ai import AIHealthResponse
from app.security.jwt import AuthUser
from app.services.llm.health import get_ollama_health

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ai-health", response_model=AIHealthResponse)
async def get_ai_health(
    request: Request,
    _user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> AIHealthResponse:
    """Return Ollama health + provider count.

    ollama_health: value set by the startup probe on app.state.ollama_health.
      "healthy" - responded < 5s
      "slow"    - responded >= 5s
      "down"    - unreachable / error
      "unknown" - probe not yet run

    providers_configured_count: total number of ai_providers rows across ALL
    projects. This is the count the admin dashboard displays to confirm
    which projects have an AI provider configured.
    """
    ollama_status = get_ollama_health(request.app)

    count_result = await db.execute(select(func.count(AIProvider.id)))
    providers_count = count_result.scalar_one() or 0

    return AIHealthResponse(
        ollama_health=ollama_status,
        providers_configured_count=int(providers_count),
    )
