"use client";

import type { EventItem, TlpName } from "@/app/api-client";
import { BrandProvenanceBadge } from "@/app/events/EventsClient";
import { TypeBadge } from "@/app/sources/components/TypeBadge";
import { formatRelativeTime } from "@/app/sources/lib/relativeTime";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// TLP badge color map — matches DashboardEventsList / EventDetailDrawer pattern
const TLP_STYLE: Record<string, { bg: string; fg: string; border: string }> = {
  clear: { bg: "rgba(136,135,128,0.15)", fg: "#888780", border: "#888780" },
  green: { bg: "rgba(29,158,117,0.15)", fg: "#9FE1CB", border: "#1D9E75" },
  amber: { bg: "rgba(239,159,39,0.15)", fg: "#EF9F27", border: "#EF9F27" },
  "amber+strict": { bg: "rgba(239,159,39,0.25)", fg: "#EF9F27", border: "#EF9F27" },
  red: { bg: "rgba(220,38,38,0.15)", fg: "#fca5a5", border: "#dc2626" },
};

const NULL_TLP_STYLE = { bg: "rgba(136,135,128,0.10)", fg: "#888780", border: "#888780" };

// BbotProvenanceBadge — rendered when event.source_type === "bbot".
// Height: h-4 (16px), horizontal padding: px-2 (8px), font-mono text-xs (12px).
// Signal-amber left-border (border-l-2 border-[var(--brand-signal)]) per 11-UI-SPEC §Surface 7.
function BbotProvenanceBadge({ event }: { event: EventItem }) {
  const tooltipText = event.easm_scan_id
    ? `BBOT scan — ${new Date(event.observed_at).toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      })}`
    : "BBOT (historical scan)";

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex items-center h-4 px-2 border-l-2 border-[var(--brand-signal)] text-[12px] font-mono font-medium uppercase tracking-[0.15em] text-muted-foreground rounded-sm">
            BBOT
          </span>
        </TooltipTrigger>
        <TooltipContent>{tooltipText}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function TlpBadge({ tlp }: { tlp: TlpName | null }) {
  const style = tlp ? (TLP_STYLE[tlp] ?? NULL_TLP_STYLE) : NULL_TLP_STYLE;
  return (
    <Badge
      variant="outline"
      className="brand-caption"
      style={{
        backgroundColor: style.bg,
        color: style.fg,
        borderColor: style.border,
      }}
    >
      {tlp ?? "\u2014"}
    </Badge>
  );
}

type Props = {
  items: EventItem[];
  loading: boolean;
  onRowClick: (id: string) => void;
};

const SKELETON_ROWS = 5;

export function EventsTable({ items, loading, onRowClick }: Props) {
  const headers = (
    <TableHeader>
      <TableRow>
        <TableHead>Title</TableHead>
        <TableHead style={{ width: 80 }}>Type</TableHead>
        <TableHead style={{ width: 72 }}>TLP</TableHead>
        <TableHead style={{ width: 88 }}>ATT&amp;CK</TableHead>
        <TableHead style={{ width: 120 }}>Source</TableHead>
        <TableHead style={{ width: 100 }}>Observed</TableHead>
      </TableRow>
    </TableHeader>
  );

  if (loading) {
    return (
      <Table>
        {headers}
        <TableBody>
          {Array.from({ length: SKELETON_ROWS }).map((_, i) => (
            <TableRow key={i} data-testid="events-skeleton-row">
              <TableCell colSpan={6}>
                <div className="animate-pulse bg-muted rounded h-4 w-full" />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );
  }

  return (
    <Table>
      <caption className="sr-only">Events list</caption>
      {headers}
      <TableBody>
        {items.map((evt) => (
          <TableRow
            key={evt.id}
            data-testid="events-row"
            data-event-id={evt.id}
            tabIndex={0}
            onClick={() => onRowClick(evt.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onRowClick(evt.id);
              }
            }}
            className="cursor-pointer hover:bg-card h-12"
          >
            <TableCell
              className="truncate"
              style={{ maxWidth: "60ch" }}
              title={evt.title ?? undefined}
            >
              {evt.title ?? "Untitled event"}
            </TableCell>
            <TableCell>
              <div className="flex items-center gap-1">
                {evt.source_type ? <TypeBadge feed_type={evt.source_type} /> : null}
                {evt.source_type === "bbot" && <BbotProvenanceBadge event={evt} />}
                {evt.source_type === "brand-monitor" && <BrandProvenanceBadge event={evt} />}
              </div>
            </TableCell>
            <TableCell>
              <TlpBadge tlp={evt.tlp} />
            </TableCell>
            <TableCell>
              <span className="brand-caption text-muted-foreground">
                {evt.attack_techniques.length > 0
                  ? `${evt.attack_techniques.length} TTPs`
                  : "\u2014"}
              </span>
            </TableCell>
            <TableCell className="truncate" style={{ maxWidth: 120 }}>
              {evt.source_name ?? "\u2014"}
            </TableCell>
            <TableCell>{formatRelativeTime(evt.observed_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
