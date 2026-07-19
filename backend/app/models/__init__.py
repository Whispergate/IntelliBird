"""SQLAlchemy models. Import submodules so Base.metadata is complete."""
from __future__ import annotations

from app.models.base import Base  # noqa: F401
from app.models import sources, events, attack, graph, markings, tags, projects  # noqa: F401
from app.models.cve_details import CveDetails  # noqa: F401
from app.models.filter_presets import FilterPreset  # noqa: F401
from app.models.users import User # noqa: F401 - AUTH-01
from app.models.projects import (# noqa: F401 - PRJ-01, PRJ-02, PRJ-05
    EngagementType,
    LEGACY_PROJECT_ID,
    Project,
    ProjectMembership,
    ProjectRole,
    ProjectScopeRow,
    ProjectSource,
    ScopeType,
)
from app.models.brand import BrandMatch, BrandTerm # noqa: F401 - BRP-01..05
from app.models.easm import EASMCredential, EASMFinding, EASMScan # noqa: F401 - EASM
from app.models.assets import AssetNote # noqa: F401 - ASSET-NOTE
from app.models.scoring import EventScoreOverride, ProjectScoringRules # noqa: F401 - SCR-01, SCR-03
from app.models.sources import (# noqa: F401 - MON-01, MON-03
    MaintenanceWindow,
    Source,
    SourceIngestStats,
)
from app.models.tiber import (# noqa: F401 - TIBER-01..03, AI-08
    TiberReport,
    TiberActorProfile,
    TiberScenario,
    ProjectTiberState,
    ReportExport,
)
from app.models.iocs import IOC, IOCEventLink # noqa: F401 - IOC-01, IOC-08
from app.models.enrichment import EnrichmentProvider, IOCEnrichment # noqa: F401 #
from app.models.cib_clusters import CibCluster # noqa: F401 - DISINFO-02

__all__ = [
    "Base",
    "AssetNote",
    "EventScoreOverride",
    "IOC",
    "IOCEventLink",
    "MaintenanceWindow",
    "ProjectScoringRules",
    "Source",
    "SourceIngestStats",
]
