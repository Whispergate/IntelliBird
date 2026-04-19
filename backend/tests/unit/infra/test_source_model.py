"""INFRA-01: Source ORM model exposes credentials_key_version."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
os.environ.setdefault("SECRET_KEY", "a" * 64)
os.environ.setdefault("REDIS_URL", "redis://r:6379/0")

from app.models.sources import Source  # noqa: E402


def test_source_has_credentials_key_version_attr() -> None:
    assert hasattr(Source, "credentials_key_version")
    col = Source.__table__.c["credentials_key_version"]
    assert col.nullable is False
    # server_default is a DefaultClause wrapping a TextClause
    assert str(col.server_default.arg) == "1"


def test_source_credentials_key_version_is_integer() -> None:
    from sqlalchemy import Integer
    col = Source.__table__.c["credentials_key_version"]
    assert isinstance(col.type, Integer)
