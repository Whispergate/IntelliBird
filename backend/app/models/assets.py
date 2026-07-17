"""Asset note ORM — project asset surface.

The only write-state on the asset inventory surface. Assets themselves are a
query-time aggregation over `easm_findings`; notes are the one stored artefact
per asset (keyed on the same (project_id, bbot_event_type, canonical_target)
tuple that makes easm_findings unique).

Notes are anchored to the project, NOT to any specific `easm_findings` row —
scan cleanup does not drop notes (RESEARCH §Pitfall 7).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func


from app.models.base import Base


class AssetNote(Base):
    """Operator-writable free-text note on a project asset.

    Key tuple: (project_id, bbot_event_type, canonical_target) — matches the
    dedup key of `easm_findings`. UNIQUE at the DB level so upserts are safe.
    """

    __tablename__ = "asset_notes"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "bbot_event_type",
            "canonical_target",
            name="uq_asset_notes_project_type_target",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bbot_event_type: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_target: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
