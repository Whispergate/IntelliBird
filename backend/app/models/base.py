"""SQLAlchemy declarative base + shared column helpers."""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root declarative base for all IntelliBird ORM models."""
    pass
