"""JSON → IOCImportRow parser (Phase 22 / IOC-02).

Accepts a top-level JSON array of objects; each object has the same shape as
the CSV row (incl. optional `project_id` + `source`).
"""
from __future__ import annotations

import json
from typing import Iterator

from pydantic import ValidationError

from app.schemas.iocs import IOCImportRow
from app.services.ioc_import.csv_parser import IOCImportTooLarge, MAX_IMPORT_ROWS


def parse_json_rows(data: bytes) -> Iterator[IOCImportRow]:
    """Stream rows from a JSON array blob.

    Raises:
        ValueError: payload is not valid JSON or is not a top-level array.
        IOCImportTooLarge: array length exceeds ``MAX_IMPORT_ROWS``.
    """
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid_json: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError("expected top-level array")
    if len(payload) > MAX_IMPORT_ROWS:
        raise IOCImportTooLarge(f"row count exceeds {MAX_IMPORT_ROWS}")
    for line_no, raw in enumerate(payload, start=1):
        if not isinstance(raw, dict):
            yield IOCImportRow(
                type="ip", value="<bad>", line=line_no, error="expected_object"
            )
            continue
        # Normalise the literal 'global' shorthand for project_id.
        if isinstance(raw.get("project_id"), str) and raw["project_id"].lower() == "global":
            raw = {**raw, "project_id": None}
        try:
            row = IOCImportRow(**raw)
            row.line = line_no
            yield row
        except ValidationError as exc:
            yield IOCImportRow(
                type="ip",
                value=str(raw.get("value") or "<missing>"),
                line=line_no,
                error=str(exc.errors()[0]["msg"]) if exc.errors() else str(exc),
            )


__all__ = ["parse_json_rows"]
