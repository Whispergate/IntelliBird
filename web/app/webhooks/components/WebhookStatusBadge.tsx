"use client";

import { Badge } from "@/components/ui/badge";
import type { Webhook } from "@/app/api-client";

type Variant = { label: string; bg: string; fg: string };

const VARIANTS: Record<string, Variant> = {
  ok:            { label: "Delivered",      bg: "rgba(29, 158, 117, 0.15)",  fg: "#1D9E75" },
  http_error:    { label: "HTTP error",     bg: "rgba(220, 38, 38, 0.15)",   fg: "hsl(var(--destructive))" },
  network_error: { label: "Network error",  bg: "rgba(220, 38, 38, 0.15)",   fg: "hsl(var(--destructive))" },
  timeout:       { label: "Timeout",        bg: "rgba(239, 159, 39, 0.15)",  fg: "#EF9F27" },
  never:         { label: "Never delivered", bg: "rgba(128, 128, 128, 0.12)", fg: "#888" },
  disabled:      { label: "Auto-disabled",  bg: "rgba(239, 159, 39, 0.2)",   fg: "#EF9F27" },
};

export function WebhookStatusBadge({ webhook }: { webhook: Webhook }) {
  let key: string = "never";
  if (!webhook.enabled && webhook.consecutive_failures >= 5) {
    key = "disabled";
  } else if (webhook.last_delivery_status) {
    key = webhook.last_delivery_status;
  }
  const v = VARIANTS[key] ?? VARIANTS.never;
  return (
    <Badge
      variant="outline"
      className="text-xs"
      style={{ backgroundColor: v.bg, color: v.fg, borderColor: v.fg }}
    >
      {v.label}
    </Badge>
  );
}
