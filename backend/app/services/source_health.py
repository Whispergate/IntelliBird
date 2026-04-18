"""Silent-failure counter maintenance for SRC-06.

Called from each worker's _impl function after a successful batch.
Caller MUST commit the session (mirrors app.ingest.normalise pattern).

State machine:
  inserted_count == 0  → silent_failure_count += 1
  inserted_count >= 1  → silent_failure_count = 0
  inserted_count < 0   → ValueError (caller bug)

Plan 02's _effective_status reads INGEST_SILENT_FAILURE_THRESHOLD and
surfaces 'silent' in SourceResponse when the counter crosses the threshold
AND last_status == 'ok'.
"""
from __future__ import annotations

import uuid

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.sources import Source


def update_silent_failure_count(
    session: Session,
    source_id: uuid.UUID,
    inserted_count: int,
) -> None:
    """Increment or reset sources.silent_failure_count. Caller commits.

    State machine:
    - inserted_count == 0  → silent_failure_count = silent_failure_count + 1
    - inserted_count >= 1  → silent_failure_count = 0
    - inserted_count < 0   → raises ValueError

    This function only executes an UPDATE — it does NOT call session.commit().
    The caller (worker _impl success path) owns the transaction boundary.
    """
    if inserted_count < 0:
        raise ValueError(
            f"inserted_count must be >= 0, got {inserted_count!r}"
        )

    if inserted_count == 0:
        values = {"silent_failure_count": Source.silent_failure_count + 1}
    else:
        values = {"silent_failure_count": 0}

    stmt = update(Source).where(Source.id == source_id).values(**values)
    session.execute(stmt)
