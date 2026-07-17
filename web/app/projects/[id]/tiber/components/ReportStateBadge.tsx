"use client";

/**
 * ReportStateBadge — displays TIBER report state (draft / published / archived).
 * UI-SPEC §"Report State Colour Map".
 */

import type { ReportState } from "../lib/api";

interface ReportStateBadgeProps {
  state: ReportState;
  className?: string;
}

const STATE_STYLES: Record<ReportState, string> = {
  draft: "bg-yellow-500/15 text-yellow-300 border-yellow-600",
  published: "bg-green-500/15 text-green-300 border-green-700",
  archived: "bg-muted text-muted-foreground border-muted-foreground/40",
};

const STATE_LABELS: Record<ReportState, string> = {
  draft: "Draft",
  published: "Published",
  archived: "Archived",
};

export function ReportStateBadge({ state, className = "" }: ReportStateBadgeProps) {
  return (
    <span
      className={[
        "inline-flex items-center rounded-sm border px-1.5 brand-caption",
        STATE_STYLES[state],
        className,
      ].join(" ")}
    >
      {STATE_LABELS[state]}
    </span>
  );
}
