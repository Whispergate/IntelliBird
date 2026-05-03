"""027 — taxii_clients table.

Phase 26 / TAXII-03: Per-partner API key store for TAXII 2.1 outbound server.

Stub — full DDL implemented in plan 26-02.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "027_taxii_clients"
down_revision: Union[str, None] = "026_threat_actors_campaigns_audit"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    pass  # stub — DDL added in plan 26-02


def downgrade() -> None:
    pass  # stub — drop added in plan 26-02
