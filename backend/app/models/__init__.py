"""SQLAlchemy models. Import submodules so Base.metadata is complete."""
from __future__ import annotations

from app.models.base import Base  # noqa: F401
from app.models import sources, events, attack, graph, markings, tags  # noqa: F401
from app.models.cve_details import CveDetails  # noqa: F401
from app.models.filter_presets import FilterPreset  # noqa: F401
from app.models.users import User  # noqa: F401  — Phase 9 / AUTH-01

__all__ = ["Base"]
