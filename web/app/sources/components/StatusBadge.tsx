"use client";

import { Badge } from "@/components/ui/badge";
import { formatRelativeTime } from "@/app/sources/lib/relativeTime";

type Props = {
  last_status: string | null;
  effective_status: string | null;
  last_polled_at: string | null;
  consecutive_failures: number;
};

// Brand-aligned status colors:
// ok = Primary teal (brand positive)
// silent = Signal amber (brand accent - warrants attention)
// rate_limited = yellow (semantic warning)
// errors = red (semantic failure)
// never_polled = Slate (brand neutral)
const STATUS_STYLE: Record<string, { bg: string; fg: string; border: string }> = {
  ok: { bg: "rgba(29, 158, 117, 0.15)", fg: "#9FE1CB", border: "#1D9E75" },
  rate_limited: { bg: "rgba(234, 179, 8, 0.15)", fg: "#fde68a", border: "#eab308" },
  http_error: { bg: "rgba(220, 38, 38, 0.15)", fg: "#fca5a5", border: "#dc2626" },
  network_error: { bg: "rgba(220, 38, 38, 0.15)", fg: "#fca5a5", border: "#dc2626" },
  parse_error: { bg: "rgba(220, 38, 38, 0.15)", fg: "#fca5a5", border: "#dc2626" },
  silent: { bg: "rgba(239, 159, 39, 0.15)", fg: "#EF9F27", border: "#EF9F27" },
};

const NEVER_POLLED_STYLE = { bg: "rgba(136, 135, 128, 0.15)", fg: "#888780", border: "#888780" };

const STATUS_LABEL: Record<string, string> = {
  ok: "OK",
  rate_limited: "RATE LIMITED",
  http_error: "HTTP ERROR",
  network_error: "NETWORK ERROR",
  parse_error: "PARSE ERROR",
  silent: "SILENT",
};

export function StatusBadge({
  last_status,
  effective_status,
  last_polled_at,
  consecutive_failures,
}: Props) {
  const status = effective_status ?? last_status;
  const style = status
    ? STATUS_STYLE[status] ?? NEVER_POLLED_STYLE
    : NEVER_POLLED_STYLE;
  const label = status
    ? STATUS_LABEL[status] ?? status.toUpperCase()
    : "NEVER POLLED";
  const relTime = formatRelativeTime(last_polled_at);
  const suffix = consecutive_failures > 0 ? ` · ${consecutive_failures} fails` : "";
  const titleAttr = last_polled_at ?? "Never polled";

  return (
    <div title={titleAttr} className="flex flex-col gap-1 items-start">
      <Badge
        variant="outline"
        className="brand-caption"
        style={{
          backgroundColor: style.bg,
          color: style.fg,
          borderColor: style.border,
        }}
      >
        {label}
      </Badge>
      <span className="text-xs text-muted-foreground">
        {relTime}
        {suffix}
      </span>
    </div>
  );
}
