"use client";

import { Badge } from "@/components/ui/badge";
import type { EngagementType } from "../lib/api";

/**
 * EngagementTypeBadge - colour-coded pill for a project engagement type.
 *
 * Colours per 10-UI-SPEC §Component Inventory:
 *   - tiber → signal amber left trim (reserved; flags TIBER-engaged projects)
 *   - red_team / bbest → mist trim
 *   - internal / intel_only → slate trim
 *
 * Signal amber is reserved for primary CTAs + the TIBER trim ONLY (UI-SPEC
 * §Color §Accent reserved-for list).
 */

const ENGAGEMENT_LABELS: Record<EngagementType, string> = {
  red_team: "Red Team",
  tiber: "TIBER",
  bbest: "BBEST",
  internal: "Internal",
  intel_only: "Intel-only",
};

const ENGAGEMENT_COLOR: Record<EngagementType, { border: string; fill: string; fg: string }> = {
  red_team:   { border: "var(--brand-mist)",   fill: "rgba(159,225,203,0.20)", fg: "var(--brand-mist)" },
  tiber:      { border: "var(--brand-signal)", fill: "rgba(239,159,39,0.15)",  fg: "var(--brand-signal)" },
  bbest:      { border: "var(--brand-mist)",   fill: "rgba(159,225,203,0.20)", fg: "var(--brand-mist)" },
  internal:   { border: "var(--brand-slate)",  fill: "rgba(136,135,128,0.15)", fg: "var(--brand-slate)" },
  intel_only: { border: "var(--brand-slate)",  fill: "rgba(136,135,128,0.15)", fg: "var(--brand-slate)" },
};

export function EngagementTypeBadge({ type }: { type: EngagementType }) {
  const label = ENGAGEMENT_LABELS[type] ?? type;
  const c = ENGAGEMENT_COLOR[type] ?? ENGAGEMENT_COLOR.internal;
  // border-l-4 gives the left-border trim effect UI-SPEC specifies. The Badge
  // `outline` variant strips its own border so our inline style wins.
  return (
    <Badge
      variant="outline"
      className="brand-caption border-l-4"
      style={{
        backgroundColor: c.fill,
        borderLeftColor: c.border,
        color: c.fg,
      }}
    >
      {label}
    </Badge>
  );
}
