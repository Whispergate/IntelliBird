"use client";

/**
 * SourceHealthTable - shadcn Table listing all source health metrics.
 * MON-04 dashboard requirement.
 *
 * Columns:
 *   Name (clickable → opens MonitoringConfigDrawer)
 *   Feed type
 *   Last event (relative - "5m ago", "2h ago", "Never")
 *   SLA badge (SilenceBadge)
 *   Silent failures (yellow if ≥ 3)
 *   Sparkline (IngestSparkline 120×32)
 *   Parse error rate 1h (red if > 50%)
 *   Drift severity pill (HIGH red / MEDIUM amber / null grey)
 */

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card } from "@/components/ui/card";
import { SilenceBadge } from "./SilenceBadge";
import { IngestSparkline } from "./IngestSparkline";
import type { MonitoringSourceRow } from "./MonitoringConfigDrawer";
import { formatRelativeTime } from "@/app/sources/lib/relativeTime";

// Per CONTEXT.md: INGEST_SILENT_FAILURE_THRESHOLD = 3 (pattern)
const SILENT_FAILURE_WARN_THRESHOLD = 3;

const DRIFT_SEVERITY_STYLES: Record<string, React.CSSProperties> = {
  HIGH: {
    background: "rgba(220,38,38,0.15)",
    border: "1px solid #dc2626",
    color: "#fca5a5",
  },
  MEDIUM: {
    background: "rgba(239,159,39,0.15)",
    border: "1px solid #EF9F27",
    color: "#EF9F27",
  },
};

function DriftPill({ severity }: { severity: string | null }) {
  if (!severity) {
    return (
      <span
        className="brand-caption h-5 px-2 inline-flex items-center rounded text-xs"
        style={{
          background: "rgba(136,135,128,0.10)",
          border: "1px solid #888780",
          color: "#888780",
        }}
      >
        OK
      </span>
    );
  }
  const style =
    DRIFT_SEVERITY_STYLES[severity.toUpperCase()] ?? DRIFT_SEVERITY_STYLES.MEDIUM;
  return (
    <span
      className="brand-caption h-5 px-2 inline-flex items-center rounded text-xs"
      style={style}
    >
      {severity.toUpperCase()}
    </span>
  );
}

type SourceHealthTableProps = {
  rows: MonitoringSourceRow[];
  onRowClick: (row: MonitoringSourceRow) => void;
};

export function SourceHealthTable({ rows, onRowClick }: SourceHealthTableProps) {
  if (rows.length === 0) {
    return (
      <Card>
        <div className="py-16 text-center">
          <p className="text-muted-foreground text-sm">
            No active sources found.
          </p>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Source</TableHead>
            <TableHead style={{ width: 90 }}>Type</TableHead>
            <TableHead style={{ width: 110 }}>Last event</TableHead>
            <TableHead style={{ width: 110 }}>SLA status</TableHead>
            <TableHead style={{ width: 90 }}>Silent fails</TableHead>
            <TableHead style={{ width: 130 }}>Ingest (7d)</TableHead>
            <TableHead style={{ width: 110 }}>Parse err 1h</TableHead>
            <TableHead style={{ width: 90 }}>Drift</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const silentWarn =
              row.silent_failure_count >= SILENT_FAILURE_WARN_THRESHOLD;
            const parseErrHigh = row.parse_error_rate_1h > 0.5;
            const sparklineData = row.sparkline.map((total, i) => ({
              bucket: String(i),
              total,
            }));

            return (
              <TableRow
                key={row.id}
                className="cursor-pointer hover:bg-muted/50"
                onClick={() => onRowClick(row)}
              >
                <TableCell className="font-medium">{row.name}</TableCell>
                <TableCell>
                  <span className="brand-caption text-xs uppercase text-muted-foreground">
                    {row.feed_type}
                  </span>
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {formatRelativeTime(row.last_event_at)}
                </TableCell>
                <TableCell>
                  <SilenceBadge
                    lastEventAt={row.last_event_at}
                    slaSec={row.silence_sla_seconds}
                    slaBreached={row.sla_breached}
                  />
                </TableCell>
                <TableCell>
                  <span
                    className="text-sm font-mono"
                    style={
                      silentWarn
                        ? { color: "#EF9F27" }
                        : { color: "var(--muted-foreground)" }
                    }
                  >
                    {row.silent_failure_count}
                  </span>
                </TableCell>
                <TableCell>
                  <IngestSparkline data={sparklineData} />
                </TableCell>
                <TableCell>
                  <span
                    className="text-sm font-mono"
                    style={
                      parseErrHigh
                        ? { color: "#fca5a5" }
                        : { color: "var(--muted-foreground)" }
                    }
                  >
                    {(row.parse_error_rate_1h * 100).toFixed(1)}%
                  </span>
                </TableCell>
                <TableCell>
                  <DriftPill severity={row.drift_severity} />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Card>
  );
}
