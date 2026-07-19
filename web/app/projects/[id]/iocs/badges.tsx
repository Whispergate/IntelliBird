"use client";

/**
 * IOC badge primitives - colour maps mirror 22-UI-SPEC §Color.
 * Used by IOC table, IOC detail drawer header, and EventDetailDrawer IOCs section.
 */

import type { IOCType, IOCStatus, IOCSource } from "@/app/api-client";

const NETWORK_TYPES: ReadonlySet<IOCType> = new Set([
  "ip",
  "ipv6",
  "domain",
  "url",
  "email",
]);
const FILE_TYPES: ReadonlySet<IOCType> = new Set([
  "sha256",
  "sha1",
  "md5",
  "filename",
  "mutex",
  "registry_key",
]);
const FINANCIAL_TYPES: ReadonlySet<IOCType> = new Set(["btc", "eth"]);

export function TypeBadge({ type }: { type: IOCType }) {
  let cls: string;
  if (NETWORK_TYPES.has(type)) {
    cls = "bg-teal-900/40 text-teal-300";
  } else if (FILE_TYPES.has(type)) {
    cls = "bg-[var(--brand-signal)]/20 text-[var(--brand-signal)]";
  } else if (FINANCIAL_TYPES.has(type)) {
    cls = "bg-purple-900/40 text-purple-300";
  } else {
    cls = "bg-muted text-muted-foreground";
  }
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-sm text-[12px] font-medium font-mono uppercase ${cls}`}
    >
      {type}
    </span>
  );
}

export function StatusPill({ status }: { status: IOCStatus }) {
  const map: Record<IOCStatus, string> = {
    active: "bg-green-500/15 text-green-300 border-green-700",
    expired: "bg-muted text-muted-foreground border-border",
    whitelisted:
      "bg-[var(--brand-signal)]/15 text-[var(--brand-signal)] border-[var(--brand-signal)]/40",
  };
  return (
    <span
      className={`inline-flex items-center rounded-sm border px-1.5 py-px brand-caption uppercase ${map[status]}`}
    >
      {status}
    </span>
  );
}

export function ConfidenceBadge({
  confidence,
  compact = false,
}: {
  confidence: string | number;
  compact?: boolean;
}) {
  const n = typeof confidence === "string" ? Number(confidence) : confidence;
  let label: string;
  let cls: string;
  if (n >= 0.8) {
    label = "High";
    cls = "bg-green-500/15 text-green-300";
  } else if (n >= 0.5) {
    label = "Med";
    cls = "bg-muted text-muted-foreground";
  } else {
    label = "Low";
    cls = "bg-orange-500/15 text-orange-300";
  }
  const value = isFinite(n) ? n.toFixed(2) : String(confidence);
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-sm px-1.5 py-px brand-caption uppercase ${cls}`}
    >
      <span>{label}</span>
      {!compact && (
        <span className="font-mono text-[12px]">· {value}</span>
      )}
    </span>
  );
}

export function SourceBadge({ source }: { source: IOCSource }) {
  if (source === "manual") {
    return <span className="text-muted-foreground brand-caption">manual</span>;
  }
  let cls: string;
  if (source === "csv" || source === "json" || source === "stix") {
    cls = "bg-muted text-muted-foreground border-border";
  } else if (source === "event") {
    cls = "bg-card text-foreground border-border";
  } else {
    cls = "bg-card/60 text-muted-foreground border-border/60 italic";
  }
  return (
    <span
      className={`inline-flex items-center rounded-sm border px-1.5 py-px brand-caption uppercase ${cls}`}
    >
      {source}
    </span>
  );
}
