---
phase: 30-notification-channels
plan: "07"
subsystem: ui
tags: [nextjs, react, zod, react-hook-form, webhooks, notifications]

requires:
  - phase: 30-notification-channels/30-05
    provides: backend webhook delivery service for email/pagerduty/opsgenie/ntfy
  - phase: 30-notification-channels/30-06
    provides: admin CRUD router for TAXII partner keys (same phase, webhook backend context)

provides:
  - Widened destination_type Zod enum to 8 types in webhookSchema.ts
  - Per-type auth_enc builders (email, pagerduty, opsgenie, ntfy) in buildCreatePayload/buildUpdatePayload
  - Conditional credential sections in WebhookDialog for all 4 new types
  - URL pre-fill on type selection (pagerduty, opsgenie)
  - WebhookTypeBadge labels and brand colors for email, pagerduty, opsgenie, ntfy
  - api-client.generated.ts destination_type union widened to 8 values

affects:
  - webhooks admin UI
  - notification channel delivery

tech-stack:
  added: []
  patterns:
    - "DESTINATION_DEFAULT_URLS map for per-type URL pre-fill on select change"
    - "Per-type _authFromValues branches producing structured JSON in bearer token payload"
    - "Conditional JSX blocks keyed on watch('destination_type') for credential sections"

key-files:
  created: []
  modified:
    - web/app/webhooks/lib/webhookSchema.ts
    - web/app/webhooks/components/WebhookDialog.tsx
    - web/app/webhooks/components/WebhookTypeBadge.tsx
    - web/app/api-client.generated.ts

key-decisions:
  - "Email/PagerDuty/Opsgenie/ntfy credentials serialised as JSON inside bearer token field for backend auth_enc shaping — avoids new API surface"
  - "api-client.generated.ts destination_type union hand-widened rather than re-running openapi-typescript (stack not running in CI)"
  - "STARTTLS toggle implemented as native checkbox (Switch component not imported in dialog)"

patterns-established:
  - "DESTINATION_DEFAULT_URLS exported from webhookSchema.ts — type change handler reads from this map to pre-fill URL"
  - "Auth credential for new types encoded as JSON string inside WebhookAuth.bearer.token — backend unpacks per type"

requirements-completed: [NOTIF-01, NOTIF-02, NOTIF-03, NOTIF-04, NOTIF-05]

duration: 18min
completed: "2026-05-04"
---

# Phase 30 Plan 07: Notification Channels Frontend Summary

**Webhook admin UI extended with 8-type dropdown, per-type credential forms (email SMTP, PagerDuty routing key, Opsgenie API key, ntfy bearer token), and distinct type badges for all 4 new destination types.**

## Performance

- **Duration:** 18 min
- **Started:** 2026-05-04T15:00:00Z
- **Completed:** 2026-05-04T15:18:00Z
- **Tasks:** 2 auto + 1 checkpoint (auto-approved)
- **Files modified:** 4

## Accomplishments

- Zod enum in `webhookSchema.ts` widened from 4 to 8 types; per-type credential fields added; `buildCreatePayload`/`buildUpdatePayload` produce correct `auth_enc` shapes per type
- `WebhookDialog.tsx` shows conditional credential sections for email (from/to/username/password/STARTTLS), pagerduty (routing_key), opsgenie (api_key + EU hint), ntfy (optional bearer token); URL pre-fills on type selection for pagerduty and opsgenie
- `WebhookTypeBadge.tsx` renders distinct brand colors — indigo (email), green (PagerDuty), orange (Opsgenie), purple (ntfy)
- `api-client.generated.ts` destination_type union hand-widened so `DestinationType` includes all 8 values
- `tsc --noEmit` baseline unchanged: only 2 pre-existing test errors remain

## Task Commits

Per IntelliBird MEMORY constraint (`feedback_no_auto_commit`), commits are authored by the user (Lavender-dll). Files staged for commit:

1. **Task 1: Widen Zod schema + per-type auth_enc builders** — staged: `web/app/webhooks/lib/webhookSchema.ts`, `web/app/api-client.generated.ts`
2. **Task 2: Conditional credential sections + type badges** — staged: `web/app/webhooks/components/WebhookDialog.tsx`, `web/app/webhooks/components/WebhookTypeBadge.tsx`
3. **Task 3: Checkpoint** — auto-approved per `workflow.auto_advance=true`

## Files Created/Modified

- `web/app/webhooks/lib/webhookSchema.ts` — destination_type enum widened to 8 types; email_from/email_to/email_username/email_password/email_use_starttls/pd_routing_key/opsgenie_api_key/ntfy_token fields added; DESTINATION_DEFAULT_URLS map; _authFromValues branches for all 4 new types
- `web/app/webhooks/components/WebhookDialog.tsx` — type dropdown extended to 8 options; handleTypeChange pre-fills URL from DESTINATION_DEFAULT_URLS; conditional JSX for email/pagerduty/opsgenie/ntfy credential sections; authTouched extended to cover new credential dirty fields
- `web/app/webhooks/components/WebhookTypeBadge.tsx` — STYLES record extended with email (indigo), pagerduty (green), opsgenie (orange), ntfy (purple) entries
- `web/app/api-client.generated.ts` — destination_type union in TestSendRequest, WebhookCreate, WebhookResponse widened to include email/pagerduty/opsgenie/ntfy

## Decisions Made

- Email/PagerDuty/Opsgenie/ntfy credentials serialised as JSON inside the `bearer.token` field for transmission — avoids adding new auth shape variants to the API client; backend's `auth_enc` handler unpacks per destination type.
- `api-client.generated.ts` hand-widened rather than regenerated — the live API server was not available during execution.
- STARTTLS toggle implemented as a native `<input type="checkbox">` rather than the shadcn `Switch` component since `Switch` was not already imported in the dialog and keeping the diff minimal was preferred.
- `lib/webhookSchema.ts` required `git add -f` due to the root `.gitignore` matching the `lib/` pattern (Python packaging artifact rule). The file is a legitimate frontend source.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] api-client.generated.ts destination_type union was stale**
- **Found during:** Task 1 (widening Zod enum)
- **Issue:** `DestinationType` is derived from `components["schemas"]["WebhookResponse"]["destination_type"]` in the generated client, which still had only the original 4 values. Widening the Zod enum without updating the generated client would produce a TypeScript error in WebhookTypeBadge's `Record<DestinationType, ...>` map.
- **Fix:** Hand-widened the three `destination_type` union literals in `api-client.generated.ts` to include all 8 types.
- **Files modified:** `web/app/api-client.generated.ts`
- **Verification:** `tsc --noEmit` error count unchanged at 2 pre-existing errors after the fix.

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug in stale generated client)
**Impact on plan:** Required to prevent TypeScript errors. No scope creep.

## Issues Encountered

- `.gitignore` line 17 (`lib/`) matched `web/app/webhooks/lib/` as a Python-packaging artifact rule. Required `git add -f` to stage the file. The file was already in the filesystem (created in prior phase work) but untracked.

## User Setup Required

None — no external service configuration required. The new destination types require credentials entered through the admin UI at runtime.

## Next Phase Readiness

- Phase 30 plan 07 complete — all 5 NOTIF requirements covered across plans 30-01 through 30-07
- Frontend webhook admin now supports all 8 destination types end-to-end
- Phase 31 (Case Management) can proceed

---
*Phase: 30-notification-channels*
*Completed: 2026-05-04*
