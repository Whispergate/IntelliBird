# Owned by: 12.1-01-PLAN
"""AssetNote ORM model tests (no DB required — pure schema introspection)."""
from __future__ import annotations

import uuid

from app.models import AssetNote
from app.models.assets import AssetNote as AssetNoteDirect


def test_asset_note_importable_from_package():
    """`from app.models import AssetNote` and direct-module import yield the same class."""
    assert AssetNote is AssetNoteDirect


def test_asset_note_tablename():
    assert AssetNote.__tablename__ == "asset_notes"


def test_asset_note_columns_exist():
    columns = {c.name for c in AssetNote.__table__.columns}
    assert columns == {
        "id",
        "project_id",
        "bbot_event_type",
        "canonical_target",
        "note",
        "updated_by",
        "updated_at",
    }


def test_asset_note_unique_constraint():
    constraint_names = {
        c.name
        for c in AssetNote.__table__.constraints
        if c.name is not None
    }
    assert "uq_asset_notes_project_type_target" in constraint_names


def test_asset_note_fk_cascade():
    fk = next(iter(AssetNote.__table__.c.project_id.foreign_keys))
    assert fk.ondelete == "CASCADE"
    assert fk.column.table.name == "projects"


def test_asset_note_instantiable():
    note = AssetNote(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        bbot_event_type="DNS_NAME",
        canonical_target="sub.example.com",
        note="operator context",
        updated_by="authentik|abc123",
    )
    assert note.bbot_event_type == "DNS_NAME"
    assert note.canonical_target == "sub.example.com"
    assert note.note == "operator context"
    assert note.updated_by == "authentik|abc123"
