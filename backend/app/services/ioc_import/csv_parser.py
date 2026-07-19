"""CSV → IOCImportRow streaming parser (IOC-02).

CONTEXT.md §"CSV columns":
  Required: type, value
  Optional: confidence, ttl_days, source, project_id, first_seen, last_seen
  Vendor shape `indicator,type` accepted via header alias.

`project_id` accepts a UUID string OR the literal `'global'` (case-insensitive)
which is converted to None - admin-only semantics enforced at the route layer.

Hard cap: 10_000 rows. Exceeding raises `IOCImportTooLarge`; the route maps
this to HTTP 413 (RESEARCH Pitfall 8).
"""
from __future__ import annotations

import csv
import io
import uuid as _uuid
from typing import Iterator

from pydantic import ValidationError

from app.schemas.iocs import IOCImportRow

MAX_IMPORT_ROWS = 10_000


class IOCImportTooLarge(Exception):
    """Raised when a CSV/JSON payload exceeds MAX_IMPORT_ROWS."""


# Alternate header names → canonical IOCImportRow field names.
# Vendor `indicator,type` shape covered via `indicator` → `value`.
_HEADER_ALIASES: dict[str, str] = {
    "indicator": "value",
    "ioc": "value",
    "ioc_value": "value",
    "ioc_type": "type",
    # CONTEXT.md §CSV columns optional-field aliases:
    "project": "project_id",
    "src": "source",
    "first_observed": "first_seen",
    "last_observed": "last_seen",
}


def _canonical_header(h: str) -> str:
    h = (h or "").strip().lower()
    return _HEADER_ALIASES.get(h, h)


def _parse_project_id(raw: str | None) -> _uuid.UUID | None:
    """Return UUID for the row's project_id column, or None.

    Empty / missing / 'global' (case-insensitive) → None. Other values must be
    valid UUIDs; ValueError surfaces to the caller and is converted into a
    per-row error (rather than aborting the whole CSV).
    """
    if raw is None:
        return None
    v = raw.strip()
    if not v or v.lower() == "global":
        return None
    return _uuid.UUID(v)


def parse_csv_rows(data: bytes) -> Iterator[IOCImportRow]:
    """Stream rows from a CSV blob.

    Yields one ``IOCImportRow`` per data row. Malformed rows yield a row with
    ``.error`` and ``.line`` set so the caller can present a per-row error
    report without aborting the whole parse.

    Raises:
        IOCImportTooLarge: when row count exceeds ``MAX_IMPORT_ROWS``.
    """
    text_data = data.decode("utf-8-sig", errors="replace")
    sample = text_data[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text_data), dialect=dialect)
    if reader.fieldnames:
        reader.fieldnames = [_canonical_header(h) for h in reader.fieldnames]

    rows_seen = 0
    for line_no, raw in enumerate(reader, start=2):  # line 1 is header
        rows_seen += 1
        if rows_seen > MAX_IMPORT_ROWS:
            raise IOCImportTooLarge(f"row count exceeds {MAX_IMPORT_ROWS}")

        payload: dict = {
            "type": (raw.get("type") or "").strip(),
            "value": (raw.get("value") or "").strip(),
            "confidence": (raw.get("confidence") or None),
            "ttl_days": (raw.get("ttl_days") or None),
            "source": ((raw.get("source") or "").strip().lower() or None),
            "first_seen": (raw.get("first_seen") or None),
            "last_seen": (raw.get("last_seen") or None),
        }
        try:
            payload["project_id"] = _parse_project_id(raw.get("project_id"))
        except ValueError as exc:
            yield IOCImportRow(
                type="ip",
                value=payload.get("value") or "<missing>",
                line=line_no,
                error=f"project_id_invalid: {exc}",
            )
            continue

        # Strip None / empty-string values so Pydantic defaults take over.
        cleaned = {k: v for k, v in payload.items() if v not in (None, "")}
        try:
            row = IOCImportRow(**cleaned)
            row.line = line_no
            yield row
        except ValidationError as exc:
            yield IOCImportRow(
                type="ip",
                value=payload.get("value") or "<missing>",
                line=line_no,
                error=str(exc.errors()[0]["msg"]) if exc.errors() else str(exc),
            )


__all__ = ["parse_csv_rows", "IOCImportTooLarge", "MAX_IMPORT_ROWS"]
