"""Content-hash helpers for feed dedup.

The UNIQUE (source_id, content_hash, observed_at) constraint on events
(migration 002) is the DB-layer enforcement; these functions produce the
`content_hash` column value. Each feed type has its own natural-identity
formula — same content from different sources is legitimately stored twice
.
"""
from __future__ import annotations

import hashlib

SEP: str = "\x1f"  # ASCII Unit Separator — cannot appear in real RSS titles,
                   # STIX IDs, CVE IDs, or URLs.


def _sha256_hex(*parts: str) -> str:
    raw = SEP.join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def rss_content_hash(source_id: str, link: str, title: str) -> str:
    """RSS: sha256(source_id || \\x1f || link || \\x1f || title) — INGR-03."""
    return _sha256_hex(source_id, link, title)


def taxii_content_hash(source_id: str, stix_id: str, modified: str) -> str:
    """TAXII/STIX: sha256(source_id || \\x1f || stix_id || \\x1f || modified).

 `modified` is the STIX SDO's revision timestamp — genuinely-modified
 objects produce a new hash and land as a new row.
"""
    return _sha256_hex(source_id, stix_id, modified)


def nvd_content_hash(source_id: str, cve_id: str, last_modified: str) -> str:
    """NVD: sha256(source_id || \\x1f || cve_id || \\x1f || lastModified)."""
    return _sha256_hex(source_id, cve_id, last_modified)
