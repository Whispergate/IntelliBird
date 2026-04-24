"""SQLAlchemy models. Import submodules so Base.metadata is complete."""
from __future__ import annotations

from app.models.base import Base  # noqa: F401
from app.models import sources, events, attack, graph, markings, tags, projects  # noqa: F401
from app.models.cve_details import CveDetails  # noqa: F401
from app.models.filter_presets import FilterPreset  # noqa: F401
from app.models.users import User  # noqa: F401  — Phase 9 / AUTH-01
from app.models.projects import (  # noqa: F401  — Phase 10 / PRJ-01, PRJ-02, PRJ-05
    EngagementType,
    LEGACY_PROJECT_ID,
    Project,
    ProjectMembership,
    ProjectRole,
    ProjectScopeRow,
    ProjectSource,
    ScopeType,
)
from app.models.brand import BrandMatch, BrandTerm  # noqa: F401  — Phase 12 / BRP-01..05
from app.models.easm import EASMCredential, EASMFinding, EASMScan  # noqa: F401  — Phase 11 EASM
from app.models.assets import AssetNote  # noqa: F401  — Phase 12.1 / ASSET-NOTE

__all__ = ["Base", "AssetNote"]
