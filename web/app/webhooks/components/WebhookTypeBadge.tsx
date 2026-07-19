"use client";

import { Badge } from "@/components/ui/badge";
import type { DestinationType } from "@/app/api-client";

const STYLES: Record<DestinationType, { bg: string; fg: string; label: string }> = {
  slack:     { bg: "rgba(97, 31, 105, 0.15)",   fg: "#611f69", label: "Slack" },
  teams:     { bg: "rgba(98, 100, 167, 0.15)",  fg: "#6264a7", label: "Teams" },
  discord:   { bg: "rgba(88, 101, 242, 0.15)",  fg: "#5865f2", label: "Discord" },
  generic:   { bg: "rgba(29, 158, 117, 0.15)",  fg: "#1D9E75", label: "Generic" },
  email:     { bg: "rgba(79, 70, 229, 0.15)",   fg: "#4f46e5", label: "Email" },
  pagerduty: { bg: "rgba(5, 150, 105, 0.15)",   fg: "#059669", label: "PagerDuty" },
  opsgenie:  { bg: "rgba(234, 88, 12, 0.15)",   fg: "#ea580c", label: "Opsgenie" },
  ntfy:      { bg: "rgba(147, 51, 234, 0.15)",  fg: "#9333ea", label: "ntfy" },
};

export function WebhookTypeBadge({ destination_type }: { destination_type: DestinationType }) {
  const s = STYLES[destination_type] ?? { bg: "rgba(100,100,100,0.15)", fg: "#666", label: destination_type };
  return (
    <Badge
      variant="outline"
      className="text-xs"
      style={{ backgroundColor: s.bg, color: s.fg, borderColor: s.fg }}
    >
      {s.label}
    </Badge>
  );
}
