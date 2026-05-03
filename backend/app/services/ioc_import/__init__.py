"""Bulk-import parsers for IOC ingestion (Phase 22 / IOC-02).

Three formats supported per CONTEXT.md §"Bulk import + STIX mapping":
  * CSV  — `parse_csv_rows(bytes)` (Content-Type: text/csv)
  * JSON — `parse_json_rows(bytes)` (Content-Type: application/json)
  * STIX 2.1 — `parse_stix_bundle(dict)` (Content-Type: application/stix+json)

Hard cap: 10_000 rows per request. Parsers raise `IOCImportTooLarge` when the
cap is exceeded; the router translates that to HTTP 413.
"""
from app.services.ioc_import.csv_parser import IOCImportTooLarge, parse_csv_rows
from app.services.ioc_import.json_parser import parse_json_rows
from app.services.ioc_import.stix_parser import STIX_TYPE_MAP, parse_stix_bundle

MAX_IMPORT_ROWS = 10_000

__all__ = [
    "parse_csv_rows",
    "parse_json_rows",
    "parse_stix_bundle",
    "STIX_TYPE_MAP",
    "IOCImportTooLarge",
    "MAX_IMPORT_ROWS",
]
