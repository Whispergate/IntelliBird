"use client";

/**
 * SilenceBadge - SLA breach badge for source health monitoring.
 * MON-04 dashboard requirement.
 *
 * Colours match brand severity palette (CONTEXT.md "Claude's Discretion"):
 *   - Red    - SLA fully breached (now - last_event_at > sla_seconds)
 *   - Amber  - Approaching SLA (within 80% consumed)
 *   - Green  - Within SLA
 *   - Grey   - No event data (last_event_at is null)
 */

type SilenceBadgeProps = {
  lastEventAt: string | null;
  slaSec: number;
  slaBreached: boolean;
};

const BADGE_STYLES = {
  red: {
    background: "rgba(220,38,38,0.15)",
    border: "1px solid #dc2626",
    color: "#fca5a5",
  },
  amber: {
    background: "rgba(239,159,39,0.15)",
    border: "1px solid #EF9F27",
    color: "#EF9F27",
  },
  green: {
    background: "rgba(29,158,117,0.15)",
    border: "1px solid #1D9E75",
    color: "#9FE1CB",
  },
  grey: {
    background: "rgba(136,135,128,0.10)",
    border: "1px solid #888780",
    color: "#888780",
  },
} as const;

type BadgeTone = keyof typeof BADGE_STYLES;

function computeTone(
  lastEventAt: string | null,
  slaSec: number,
  slaBreached: boolean,
): BadgeTone {
  if (lastEventAt === null) return "grey";
  if (slaBreached) return "red";
  const elapsedSec =
    (Date.now() - new Date(lastEventAt).getTime()) / 1000;
  if (elapsedSec / slaSec >= 0.8) return "amber";
  return "green";
}

function toneLabel(tone: BadgeTone): string {
  switch (tone) {
    case "red":    return "SLA breach";
    case "amber":  return "SLA warning";
    case "green":  return "OK";
    case "grey":   return "No data";
  }
}

export function SilenceBadge({ lastEventAt, slaSec, slaBreached }: SilenceBadgeProps) {
  const tone = computeTone(lastEventAt, slaSec, slaBreached);
  const style = BADGE_STYLES[tone];
  return (
    <span
      className="brand-caption h-6 px-2 inline-flex items-center rounded text-xs"
      style={style}
    >
      {toneLabel(tone)}
    </span>
  );
}
