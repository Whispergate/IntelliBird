"use client";

/**
 * EASMGatePreview — Phase 10 Plan 10-10 (UI-SPEC §EASMGatePreview).
 *
 * Read-only card that surfaces the three EASM gate columns pre-landed on
 * `projects` in migration 009 (plan 10-01):
 *   - active_scans_authorised       (boolean, default false)
 *   - scope_acknowledgement_text    (text | null)
 *   - active_auth_confirmed_at      (timestamptz | null)
 *
 * Phase 11 will wire these fields to an editable form — until then the gate
 * is visible to operators so they understand the shape without being able to
 * flip it. scope_acknowledgement_text is truncated to 80 chars in the display
 * (full value still lives server-side).
 *
 * Copy lock (UI-SPEC §EASMGatePreview):
 *   - Header (caption-style): "Active-scan authorisation (Phase 11)"
 *   - Footer caption: "Phase 11 wires this form live — active scans will
 *     remain blocked until all three fields are set."
 */

import type { ProjectResponse } from "../../lib/api";

const ACK_TRUNCATE_CHARS = 80;

export function EASMGatePreview({ project }: { project: ProjectResponse }) {
  const ackText = project.scope_acknowledgement_text
    ? project.scope_acknowledgement_text.length > ACK_TRUNCATE_CHARS
      ? project.scope_acknowledgement_text.slice(0, ACK_TRUNCATE_CHARS) + "…"
      : project.scope_acknowledgement_text
    : "—";

  const confirmedAt = project.active_auth_confirmed_at ?? "—";

  return (
    <div className="rounded-md border border-border bg-card p-4 space-y-3">
      <div className="brand-caption text-muted-foreground">
        Active-scan authorisation (Phase 11)
      </div>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm font-mono">
        <dt className="text-muted-foreground">active_scans_authorised:</dt>
        <dd className="text-foreground">
          {String(project.active_scans_authorised)}
        </dd>
        <dt className="text-muted-foreground">scope_acknowledgement_text:</dt>
        <dd className="text-foreground break-words">{ackText}</dd>
        <dt className="text-muted-foreground">active_auth_confirmed_at:</dt>
        <dd className="text-foreground break-all">{confirmedAt}</dd>
      </dl>
      <p className="text-xs text-muted-foreground">
        Phase 11 wires this form live — active scans will remain blocked until
        all three fields are set.
      </p>
    </div>
  );
}
