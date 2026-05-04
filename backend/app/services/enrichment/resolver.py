"""Enrichment provider resolver — Phase 23 / ENRICH-01.

Resolves the active set of enrichment providers for a given project.
Priority: per-project row (project_id=<uuid>) > global row (project_id IS NULL).

For any provider not configured per-project, the global row is used as a
fallback IF the global row has enabled=True.

Also provides the locked PROVIDER_IOC_ROUTING table specifying which
provider supports which IOC types, and re-exports PROVIDER_CHOICES from
the model layer for router convenience.

Public API:
  get_enabled_providers(session, project_id) -> list[ProviderRow]
  PROVIDER_IOC_ROUTING  dict[str, set[str]]
  PROVIDER_CHOICES      frozenset[str]         (re-exported from model)
"""
from __future__ import annotations

import logging
from typing import NamedTuple

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrichment import EnrichmentProvider
from app.models.enrichment import PROVIDER_CHOICES  # re-export for router convenience
from app.config import settings
from app.crypto import decrypt_credentials

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routing table — locked to CONTEXT.md values; do NOT add providers here.
# ---------------------------------------------------------------------------

PROVIDER_IOC_ROUTING: dict[str, set[str]] = {
    "vt":              {"ip", "ipv6", "domain", "url", "sha256", "sha1", "md5"},
    "abuseipdb":       {"ip", "ipv6"},
    "greynoise":       {"ip", "ipv6"},
    "shodan":          {"ip", "ipv6"},
    "otx":             {"domain", "sha256", "sha1", "md5"},
    "urlhaus":         {"domain", "url"},
    # Passive DNS providers (Phase 28 / ENRICH-06) — domain only
    "securitytrails":  {"domain"},
    "mnemonic":        {"domain"},
    "riskiq_community": {"domain"},
}


class ProviderRow(NamedTuple):
    """Resolved provider configuration — api_key already decrypted."""

    provider: str
    api_key: str | None         # None when credentials_enc is NULL (keyless providers)
    daily_cap: int | None       # None → unlimited
    project_scope_str: str      # "global" for fallback rows; project UUID str for per-project


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


async def get_enabled_providers(
    session: AsyncSession,
    project_id,
) -> list[ProviderRow]:
    """Return the active provider rows for a given project.

    Per-project rows (project_id = <uuid>) take precedence. For any
    provider without a per-project row, the global row (project_id IS NULL)
    is used as a fallback if it has enabled=True.

    Args:
        session:    AsyncSession bound to the current request scope.
        project_id: UUID of the project (str or uuid.UUID).

    Returns:
        List of ProviderRow namedtuples with decrypted api_key.
    """
    project_id_str = str(project_id)

    # 1. Per-project enabled rows
    per_project_stmt = select(EnrichmentProvider).where(
        EnrichmentProvider.project_id == project_id,
        EnrichmentProvider.enabled.is_(True),
    )
    per_project_result = await session.execute(per_project_stmt)
    per_project_rows = per_project_result.scalars().all()

    per_project_providers: set[str] = {row.provider for row in per_project_rows}

    # 2. Global fallback rows for providers not covered per-project
    global_rows: list[EnrichmentProvider] = []
    if len(per_project_providers) < len(PROVIDER_CHOICES):
        missing_providers = list(PROVIDER_CHOICES - per_project_providers)
        global_stmt = select(EnrichmentProvider).where(
            EnrichmentProvider.project_id.is_(None),
            EnrichmentProvider.enabled.is_(True),
            EnrichmentProvider.provider.in_(missing_providers),
        )
        global_result = await session.execute(global_stmt)
        global_rows = global_result.scalars().all()

    # 3. Build ProviderRow list
    resolved: list[ProviderRow] = []

    for row in per_project_rows:
        api_key = _decrypt_key(row)
        resolved.append(
            ProviderRow(
                provider=row.provider,
                api_key=api_key,
                daily_cap=row.daily_request_cap,
                project_scope_str=project_id_str,
            )
        )

    for row in global_rows:
        api_key = _decrypt_key(row)
        resolved.append(
            ProviderRow(
                provider=row.provider,
                api_key=api_key,
                daily_cap=row.daily_request_cap,
                project_scope_str="global",
            )
        )

    return resolved


def _decrypt_key(row: EnrichmentProvider) -> str | None:
    """Decrypt credentials_enc or return None for keyless providers."""
    if not row.credentials_enc:
        return None
    try:
        creds = decrypt_credentials(settings.SECRET_KEY, row.credentials_enc)
        return creds.get("api_key")
    except Exception:
        logger.warning(
            "enrich_resolver_decrypt_failed provider=%s project_id=%s",
            row.provider,
            row.project_id,
        )
        return None


__all__ = ["get_enabled_providers", "PROVIDER_IOC_ROUTING", "PROVIDER_CHOICES", "ProviderRow"]
