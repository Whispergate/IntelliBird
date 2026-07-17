"use client";

/**
 * FormatBadge — inline export format badge.
 * UI-SPEC §Surface 8 colour map verbatim.
 */

import type { ReportFormat } from "../lib/api";

interface FormatBadgeProps {
  format: ReportFormat;
}

export function FormatBadge({ format }: FormatBadgeProps) {
  switch (format) {
    case "markdown":
      return (
        <span className="inline-flex items-center rounded-sm border px-1.5 py-px brand-caption bg-muted text-muted-foreground border-border">
          MD
        </span>
      );
    case "pdf":
      return (
        <span className="inline-flex items-center rounded-sm border px-1.5 py-px brand-caption bg-red-500/10 text-red-300 border-red-700">
          PDF
        </span>
      );
    case "stix":
      return (
        <span className="inline-flex items-center rounded-sm border px-1.5 py-px brand-caption bg-blue-500/10 text-blue-300 border-blue-700">
          STIX
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center rounded-sm border px-1.5 py-px brand-caption bg-muted text-muted-foreground border-border">
          {format}
        </span>
      );
  }
}
