"""- Sigma rule evaluation engine.

All functions are synchronous - called from _persist_event (sync Session path).
SECURITY: evaluate_sigma_rules wraps all eval in try/except so a bad rule
never breaks event ingest.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, text, or_
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# Sigma field name → event dict key
SIGMA_FIELD_MAP: dict[str, str] = {
    "title": "title",
    "description": "description",
    "keywords": "tags",
    "threat_actor": "threat_actor",   # always None at ingest - see sigma-mapping.md
    "raw_stix_pattern": "raw_stix_pattern",
    "source": "source",
}


def _parse_sigma_rule(content: str) -> dict:
    """Parse and validate a Sigma rule YAML string.

    Returns a JSON-safe dict (rule.to_dict()) on success.
    Raises HTTPException(422) on any parse or validation error.
    """
    try:
        from sigma.rule import SigmaRule as _SigmaRule
        rule = _SigmaRule.from_yaml(content)
        cache = rule.to_dict()
        # Ensure JSON-serialisable; fall back to str()-coerced dict if needed
        try:
            json.dumps(cache)
        except (TypeError, ValueError):
            cache = _coerce_dict_to_json_safe(cache)
        return cache
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid Sigma rule: {exc}",
        ) from exc


def _coerce_dict_to_json_safe(obj: Any) -> Any:
    """Recursively coerce non-JSON-serialisable values to strings."""
    if isinstance(obj, dict):
        return {k: _coerce_dict_to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_dict_to_json_safe(v) for v in obj]
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def _build_event_dict(session: Session, event_id: uuid.UUID) -> dict:
    """Build a flat event dict for Sigma field matching.

    Returns empty dict if event not found.
    """
    from app.models.events import Event

    event = session.get(Event, event_id)
    if event is None:
        return {}

    # Resolve source name via JOIN
    source_name: str | None = None
    if event.source_id is not None:
        source_name = session.execute(
            text("SELECT name FROM sources WHERE id = :id"),
            {"id": str(event.source_id)},
        ).scalar_one_or_none()

    # Build STIX pattern string from raw_stix JSONB
    stix_str = ""
    if event.raw_stix:
        patterns = [
            obj.get("pattern", "")
            for obj in event.raw_stix.get("objects", [])
            if obj.get("pattern")
        ]
        stix_str = " ".join(patterns)

    return {
        "title": event.title or "",
        "description": event.description or "",
        "tags": event.tags or [],
        "threat_actor": None,
        "raw_stix_pattern": stix_str,
        "source": source_name or "",
    }


def _value_matches(pattern_val: str, field_val: str, modifiers: list) -> bool:
    """Test if pattern_val matches field_val given the list of Sigma modifiers.

    All comparisons are case-insensitive.
    """
    pv = pattern_val.lower()
    fv = field_val.lower()

    modifier_names = {type(m).__name__.lower() for m in modifiers}

    if "containsmodifier" in modifier_names or "contains" in modifier_names:
        return pv in fv
    if "startswithmodifier" in modifier_names or "startswith" in modifier_names:
        return fv.startswith(pv)
    if "endswithmodifier" in modifier_names or "endswith" in modifier_names:
        return fv.endswith(pv)
    if "remodifier" in modifier_names or "re" in modifier_names:
        try:
            return bool(re.search(pattern_val, field_val, re.IGNORECASE))
        except re.error:
            return False

    # Default: case-insensitive exact equality
    return pv == fv


def _evaluate_detection_item(item: Any, event_dict: dict) -> bool:
    """Evaluate a single SigmaDetectionItem against the event dict."""
    if item.field is None:
        # Keyword search - check any value in event_dict contains any pattern value
        haystack = " ".join(
            str(v) if not isinstance(v, list) else " ".join(str(e) for e in v)
            for v in event_dict.values()
            if v is not None
        ).lower()
        return any(str(v).lower() in haystack for v in item.value)

    if item.field not in SIGMA_FIELD_MAP:
        log.debug("sigma_unknown_field field=%s", item.field)
        return False

    field_val = event_dict.get(SIGMA_FIELD_MAP[item.field])
    if field_val is None:
        return False

    pattern_values = [str(v) for v in item.value]

    if isinstance(field_val, list):
        # Check if any list element matches any pattern value
        return any(
            _value_matches(pv, str(fv), item.modifiers)
            for pv in pattern_values
            for fv in field_val
        )
    else:
        return any(
            _value_matches(pv, str(field_val), item.modifiers)
            for pv in pattern_values
        )


def _evaluate_detection(detection: Any, event_dict: dict) -> bool:
    """Evaluate a SigmaDetection (OR-linked detection items)."""
    return any(
        _evaluate_detection_item(item, event_dict)
        for item in detection.detection_items
    )


def _eval_condition_expr(condition_str: str, detections: dict, event_dict: dict) -> bool:
    """Evaluate a compound condition expression.

    Supported: simple named detection, AND/OR joins, NOT prefix.
    Falls back to False + WARNING for 'all of them*' / '1 of them*'.
    """
    stripped = condition_str.strip()

    # Unsupported wildcard group conditions
    if re.search(r"(all|1|\d+)\s+of\s+(them|selection|keyword)", stripped, re.IGNORECASE):
        log.warning("sigma_unsupported_condition cond=%s", condition_str)
        return False

    # Handle OR (split first to avoid partial AND match)
    lower = stripped.lower()
    if " or " in lower:
        parts = re.split(r"\s+or\s+", stripped, flags=re.IGNORECASE)
        return any(_eval_condition_expr(p.strip(), detections, event_dict) for p in parts)

    # Handle AND
    if " and " in lower:
        parts = re.split(r"\s+and\s+", stripped, flags=re.IGNORECASE)
        return all(_eval_condition_expr(p.strip(), detections, event_dict) for p in parts)

    # Handle NOT
    if lower.startswith("not "):
        inner = stripped[4:].strip()
        return not _eval_condition_expr(inner, detections, event_dict)

    # Single named detection
    if stripped in detections:
        return _evaluate_detection(detections[stripped], event_dict)

    log.warning("sigma_unknown_condition_ref cond=%s", condition_str)
    return False


def _evaluate_condition(rule: Any, event_dict: dict) -> bool:
    """Evaluate the full rule condition against event_dict."""
    condition_list = rule.detection.condition
    condition_str = condition_list[0] if condition_list else "selection"
    detections = rule.detection.detections

    if condition_str in detections:
        return _evaluate_detection(detections[condition_str], event_dict)

    return _eval_condition_expr(condition_str, detections, event_dict)


def write_sigma_matches(
    session: Session,
    rule_name: str,
    rule_tags: list[str],
    event_id: uuid.UUID,
) -> None:
    """Write attack_technique_tags rows for a matched Sigma rule.

    Uses ON CONFLICT DO NOTHING for idempotency.
    If rule_tags is empty, uses rule_name as a pseudo-technique ID.
    """
    targets = rule_tags if rule_tags else [rule_name]
    for tag in targets:
        session.execute(
            text("""
                INSERT INTO attack_technique_tags (event_id, technique_id, tag_source, evidence_text)
                VALUES (:event_id, :technique_id, 'auto', :evidence)
                ON CONFLICT DO NOTHING
            """),
            {
                "event_id": str(event_id),
                "technique_id": tag,
                "evidence": f"Sigma rule: {rule_name}",
            },
        )


def _load_active_sigma_rules(
    session: Session,
    project_id: uuid.UUID | None,
) -> list:
    """Load enabled SigmaRules scoped to project_id (+ global) or global only."""
    from app.models.sigma_rules import SigmaRule

    stmt = select(SigmaRule).where(SigmaRule.enabled == True)  # noqa: E712

    if project_id is not None:
        stmt = stmt.where(
            or_(SigmaRule.project_id == project_id, SigmaRule.project_id.is_(None))
        )
    else:
        stmt = stmt.where(SigmaRule.project_id.is_(None))

    return list(session.execute(stmt).scalars().all())


def evaluate_sigma_rules(
    session: Session,
    event_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> None:
    """Evaluate all active Sigma rules against the event.

    Writes attack_technique_tags rows for each match, then dispatches
    rescore_project if any matches occurred.

    SAFETY: Entire function is wrapped in try/except - a bad rule or
    transient error never breaks event ingest.
    """
    try:
        from sigma.rule import SigmaRule as _SigmaRule
        from app.workers.scoring import rescore_project

        rules = _load_active_sigma_rules(session, project_id)
        if not rules:
            return

        event_dict = _build_event_dict(session, event_id)
        if not event_dict:
            return

        any_match = False
        for rule in rules:
            try:
                # Reconstruct rule from compiled cache or re-parse from content
                if rule.compiled_cache:
                    sigma_rule = _SigmaRule.from_dict(rule.compiled_cache)
                else:
                    sigma_rule = _SigmaRule.from_yaml(rule.content)

                matched = _evaluate_condition(sigma_rule, event_dict)
                if matched:
                    write_sigma_matches(session, rule.name, rule.tags or [], event_id)
                    any_match = True
            except Exception as exc:
                log.warning(
                    "sigma_rule_eval_error rule_id=%s rule_name=%s error=%r",
                    rule.id,
                    rule.name,
                    exc,
                    exc_info=True,
                )

        if any_match and project_id is not None:
            rescore_project.send(str(project_id))

    except Exception as exc:
        log.warning(
            "sigma_evaluate_error event_id=%s project_id=%s error=%r",
            event_id,
            project_id,
            exc,
            exc_info=True,
        )
