"use client";

import { Badge } from "@/components/ui/badge";
import type { DestinationType } from "@/app/api-client";

const STYLES: Record<DestinationType, { bg: string; fg: string; label: string }> = {
  slack:   { bg: "rgba(97, 31, 105, 0.15)",  fg: "#611f69", label: "Slack" },
  teams:   { bg: "rgba(98, 100, 167, 0.15)", fg: "#6264a7", label: "Teams" },
  discord: { bg: "rgba(88, 101, 242, 0.15)", fg: "#5865f2", label: "Discord" },
  generic: { bg: "rgba(29, 158, 117, 0.15)", fg: "#1D9E75", label: "Generic" },
};

export function WebhookTypeBadge({ destination_type }: { destination_type: DestinationType }) {
  const s = STYLES[destination_type];
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
