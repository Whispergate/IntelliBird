# IntelliBird Scoring Engine

This document describes the composite priority scoring system for IntelliBird events. All defaults are bundled in `backend/app/services/scoring/defaults.py` as `DEFAULT_SCORING_CONFIG`. Per-project overrides are stored in the `project_scoring_rules` table as JSONB and fall through to these defaults when empty.

---

## Default weights

The composite score is a weighted sum of four signals:

| Signal           | Default weight | Description                                              |
|------------------|---------------|----------------------------------------------------------|
| CVSS             | 50            | CVSS base score normalised to 0–1 (÷10)                 |
| Recency          | 20            | Exponential decay factor based on event age              |
| Source confidence| 15            | Source reliability rating (0.0–1.0)                      |
| Relevance        | 15            | Tag intersection with project scope (0.0 or 1.0)         |
| **Sum**          | **100**       | Weights must always sum to 100                           |

**Rationale:** The 50/20/15/15 split is a CVE-driven SOC default - CVSS carries the most weight because NVD-driven workflows treat CVSS 9.0+ as the primary signal for immediate escalation. The remaining 50 points distribute signal from feed timeliness (recency), source reliability, and project-scope relevance. This matches operator expectations from established NVD vulnerability workflows.

**Formula:**

```
score = clamp(
    w_cvss * (cvss_base_score / 10.0)
    + w_recency * recency_factor
    + w_source * source_confidence
    + w_relevance * tag_relevance,
    0, 100
)
```

Events without a real CVSS score receive a synthetic CVSS by feed type (see Synthetic CVSS section below), so the formula runs uniformly across all event types.

---

## Decay

Recency uses an exponential half-life formula. The score is **computed on read**, not stored as a decaying column - the base score (`events.score`) and the scoring timestamp (`events.scored_at`) are stored at ingest, and the decayed value is projected at query time.

**Half-life: 14 days** (default)

**Formula:**

```
decayed_score = base_score × 2^(−age_days / 14)
```

Where `age_days = (now − events.scored_at) / 86400`.

**Behaviour at key ages:**

| Age        | Decay factor | Score retained |
|------------|-------------|----------------|
| 0 days     | 1.000       | 100%           |
| 7 days     | 0.707       | ~71%           |
| 14 days    | 0.500       | 50%            |
| 28 days    | 0.250       | 25%            |
| 56 days    | 0.063       | ~6%            |

**Rationale for 14 days:** A 7-day half-life is too aggressive for compliance-tinted use cases (CVEs remain relevant for 30+ days). A 30-day half-life leaves stale CVEs feeling current. 14 days balances timeliness against retention for typical SOC review cycles.

**Implementation note:** The decay factor in `score_event()` applies at ingest time as the recency component of the weighted sum, not as a post-score multiplier. The query-time projection applies the same formula using stored `scored_at`. Pre-migration rows with `score IS NULL` are treated as tier D (score 0) for sort and filter operations.

---

## Tiers

Events are classified into five tiers based on their 0–100 score:

| Tier | Score range | Meaning                                    |
|------|-------------|--------------------------------------------|
| S    | ≥ 90        | Critical - immediate action required       |
| A    | 75–89       | High - prioritise in next review           |
| B    | 55–74       | Medium - review within standard cycle      |
| C    | 30–54       | Low - monitor, defer if resources limited  |
| D    | < 30        | Informational - background signal          |

The S tier is intentionally rare - only events with CVSS 9.0+ that are fresh (< 2–3 days old) and from a high-confidence source will typically reach S. This matches the CVSS 9.0+ escalation threshold expected by SOC operators.

Tier cutoffs are per-project overridable via the admin scoring configuration page (see Per-project overrides below).

**NULL score handling:** Pre-migration rows in the events table have `score IS NULL`. The query layer uses `COALESCE(score, 0)` for sort and filter operations, which maps unscored events to tier D. This is documented as the authoritative NULL treatment - do not treat unscored events as tier S or A.

---

## Synthetic CVSS for non-CVE events

Events without an explicit CVSS base score receive a synthetic value so the scoring formula runs uniformly. The synthetic value is assigned in `score_event()` based on feed type and brand severity.

| Event type                    | Synthetic CVSS |
|-------------------------------|----------------|
| RSS feed (general)            | 5.0            |
| TAXII (non-CVE)               | 6.0            |
| Brand match - low severity    | 3.0            |
| Brand match - medium severity | 6.0            |
| Brand match - high severity   | 8.0            |

**Priority:** If `cvss_score` is provided, it is used directly. If `brand_severity` is set and `cvss_score` is `None`, brand severity takes priority over the feed type lookup. Only when both are absent is the feed type synthetic applied.

---

## Source confidence defaults

Source confidence is a per-source reliability rating in [0.0, 1.0] that contributes up to 15 points to the composite score.

| Source type                   | Default confidence |
|-------------------------------|-------------------|
| TAXII feeds                   | 1.0               |
| NVD (CVE database)            | 1.0               |
| RSS - curated (NCSC, CISA etc.)| 0.9              |
| RSS - general                 | 0.7               |

These defaults are stored in `DEFAULT_SOURCE_CONFIDENCE` in `backend/app/services/scoring/defaults.py`. Operators can override confidence per source via the source detail admin UI (the `confidence` column on the `sources` table). The per-type defaults are applied at source creation time; the column is mutable so curated feeds can be elevated to 0.9+ without code changes.

---

## Per-project overrides

Operators can configure per-project scoring rules via the admin scoring configuration page (`/projects/{id}/scoring`). Overrides are stored as JSONB in `project_scoring_rules.rules`. Projects without a row, or with an empty `rules` JSONB, fall through to the bundled defaults.

**JSONB shape** (matches `DEFAULT_SCORING_CONFIG`):

```json
{
  "weights": {
    "cvss": 50,
    "recency": 20,
    "source": 15,
    "relevance": 15
  },
  "decay_half_life_days": 14,
  "tier_cutoffs": {
    "S": 90,
    "A": 75,
    "B": 55,
    "C": 30
  }
}
```

**Constraints enforced at save time:**

- `weights.cvss + weights.recency + weights.source + weights.relevance` must equal exactly 100.
- Each tier cutoff must be a number in [0, 100].
- Tier cutoffs must be strictly descending: `S > A > B > C`.
- `decay_half_life_days` must be a positive number.

Saving new rules bumps `project_scoring_rules.version` and automatically enqueues the `rescore_project` Dramatiq actor on the `scoring` queue to recompute scores for all existing events. A status row on the scoring config page polls `GET /api/projects/{id}/rescore/status` to show progress.

---

## Burst suppression

To prevent scoring-driven webhook floods, IntelliBird limits high-tier (S + A tier) webhook dispatches per project to a maximum of **5 fires per 1-hour rolling window**.

**Behaviour when the cap is exceeded:**

- The event is stored normally with its tier badge visible in the events list.
- The event is tagged `burst_cluster=true`.
- No webhook is dispatched for that event.
- The EventDetailDrawer shows "suppressed: cluster of N in window".

The burst suppression state is maintained in Redis using a sorted-set sliding window keyed `burst:project:{id}:high`. The check occurs in `webhook_dispatcher.py` immediately after tier classification, before fan-out.

This behaviour matches the roadmap H-1 requirement verbatim: excess events are stored and visible, not discarded.
