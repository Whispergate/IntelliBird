# Sigma Field Mapping — IntelliBird Phase 29

IntelliBird evaluates Sigma rules against a flat event dict built at ingest time.
This document lists every Sigma field IntelliBird maps, how it is sourced,
and known limitations.

## Mapped Fields

| Sigma Field | Event Source | Notes |
|-------------|-------------|-------|
| `title` | `events.title` | Direct column; empty string if NULL |
| `description` | `events.description` | Direct column; empty string if NULL |
| `keywords` | `events.tags` (ARRAY) | Keyword search checks each tag element; empty list if NULL |
| `threat_actor` | **Always `None` at ingest** | See limitation below |
| `raw_stix_pattern` | `events.raw_stix["objects"][*]["pattern"]` joined with spaces | Only populated for TAXII/STIX events |
| `source` | `sources.name` WHERE `id = events.source_id` | One extra SELECT per event eval; empty string if source missing |

## Limitations

### threat_actor Is Not Available at Ingest Time

The `threat_actor` field is extracted by the AI summariser (Phase 17) **after** ingest
and stored in `ai_suggestions` — it is NOT written back to the `events` row.

At ingest-time evaluation, `threat_actor` always resolves to `None`.
Any Sigma rule using `threat_actor:` will never match during live ingest.

**Workaround:** The `/api/admin/sigma-rules/test` test-window endpoint queries
the last 100 events and could be extended to JOIN `ai_suggestions` for
threat_actor resolution. This is deferred to a future phase.

### Unknown Fields Are Silently Skipped

Sigma fields not listed in the mapping table above evaluate to `None` and log
at DEBUG level (`sigma_unknown_field`). They do not cause errors.

### Unsupported Condition Syntax

The evaluator supports:
- `condition: selection` (simple named detection)
- `condition: keywords`
- `condition: selection AND keywords` (AND of named detections)
- `condition: selection OR selection2` (OR of named detections)
- `condition: NOT selection` (negation)

The following patterns fall back to `False` with a WARNING log:
- `condition: all of them*`
- `condition: 1 of them*`
- Complex wildcard group expansions

Most public community Sigma rules (SigmaHQ/sigma repository) use
`condition: selection` and are fully supported.

## Supported Modifiers

| Modifier | Behaviour |
|----------|-----------|
| `contains` | Case-insensitive substring match |
| `startswith` | Case-insensitive prefix match |
| `endswith` | Case-insensitive suffix match |
| `re` | Python `re.search()` match |
| (none) | Case-insensitive exact equality |
| (unsupported) | Falls back to exact equality; DEBUG log |

## Tag Write Behaviour

When a rule matches:
- One `attack_technique_tags` row is written per ATT&CK technique ID in `sigma_rules.tags`
- `tag_source = 'auto'` (same as YARA matches)
- `evidence_text = 'Sigma rule: {rule_name}'`
- `ON CONFLICT DO NOTHING` ensures idempotency on replay
- If the rule has no tags, the rule name itself is used as the pseudo-technique ID

After any matches, `rescore_project` Dramatiq actor is dispatched for the project.
