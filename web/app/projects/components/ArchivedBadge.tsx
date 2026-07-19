"use client";

import { Badge } from "@/components/ui/badge";

/**
 * ArchivedBadge - dim slate-coloured caption pill for archived projects.
 *
 * Appears next to the project name on /projects list rows where
 * `project.archived === true`. Combined with a 60% row-opacity overlay so the
 * row visually recedes.
 */
export function ArchivedBadge() {
  return (
    <Badge
      variant="outline"
      className="brand-caption"
      style={{
        backgroundColor: "rgba(136,135,128,0.15)",
        color: "var(--brand-slate)",
        borderColor: "var(--brand-slate)",
      }}
    >
      Archived
    </Badge>
  );
}

/**
 * LegacyBadge - caption-cased "Legacy data" pill pinned to the legacy
 * sentinel project row. Distinct from ArchivedBadge so operators can tell the
 * difference between "project was archived by an operator" and "sentinel row
 * holding legacy data that is read-only by design".
 */
export function LegacyBadge() {
  return (
    <Badge
      variant="outline"
      className="brand-caption"
      style={{
        backgroundColor: "rgba(136,135,128,0.15)",
        color: "var(--brand-slate)",
        borderColor: "var(--brand-slate)",
      }}
      title="Pre-project-scoping events (v1.5) retained under this sentinel project for audit."
    >
      Legacy data
    </Badge>
  );
}
