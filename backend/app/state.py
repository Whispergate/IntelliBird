"""Shared process-level state for app.main <-> app.routers.system.

INFRA-03: `decrypt_check` is set by the FastAPI lifespan hook
(app.main) on startup and read by GET /api/system/status (app.routers.system).
Breaks the circular import between main.py and system.py.

This is intentionally a plain module with a mutable attribute - not a class -
so readers see `app.state.decrypt_check` rather than instance state.
"""
from __future__ import annotations

from typing import Literal

DecryptCheckState = Literal["ok", "failed", "unknown"]

decrypt_check: DecryptCheckState = "unknown"
