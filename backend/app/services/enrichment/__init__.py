"""Enrichment service package — Phase 23 / ENRICH-01..05.

Provides quota, circuit breaker, cache, provider resolver, and unified
verdict aggregation for IOC enrichment. All external provider modules
live under enrichment.external/.

Also re-exports the regex-based IOC/text extraction layer that was
previously in services/enrichment.py (now shadowed by this package).
"""
# Re-export everything from the text-extraction module so that
# `from app.services.enrichment import enrich_event` keeps working
# after the package was introduced in Phase 23.
from app.services.enrichment._text_extraction import (  # noqa: F401
    Enrichment,
    enrich_event,
    merge_enrichment_into_event_row,
    attack_technique_tag_rows,
)
from app.services.enrichment._text_extraction import _CRED_PAIR_PATTERN  # noqa: F401
