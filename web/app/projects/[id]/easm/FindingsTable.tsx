"use client";

/**
 * FindingsTable — (UI-SPEC §Surface 3 §Findings table).
 *
 * 8-column findings table per UI-SPEC:
 *   Type (160px) | Target (flex-1, font-mono, truncate@48) | Module (140px) |
 *   Severity (100px chip) | First seen (120px) | Last seen (120px) |
 *   Status (120px) | Actions (140px)
 *
 * Row height 44px (WCAG 2.5.5 touch target — matches /events event-list density).
 *
 * Watchlist rows: signal-amber dot before lifecycle pill.
 * Dismissed rows: opacity-60 + text-muted-foreground.
 * Observer role: Actions Select disabled with tooltip.
 */

import { useState } from "react";
import { toast } from "sonner";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { EASMFinding, LifecycleStatus, Severity } from "./lib/api";
import { patchFindingLifecycle } from "./lib/api";

// ---------------------------------------------------------------------------
// Severity chip colours per UI-SPEC §Color
// ---------------------------------------------------------------------------
const SEVERITY_CLASS: Record<string, string> = {
  critical: "text-destructive font-medium",
  high: "text-orange-500 font-medium",
  medium: "text-yellow-500 font-medium",
  low: "text-muted-foreground",
};

function SeverityChip({ severity }: { severity: Severity | null }) {
  if (!severity) return <span className="text-muted-foreground">—</span>;
  const cls = SEVERITY_CLASS[severity] ?? "text-muted-foreground";
  return (
    <span className={`brand-caption uppercase ${cls}`}>{severity}</span>
  );
}

// ---------------------------------------------------------------------------
// Lifecycle pill + watchlist dot
// ---------------------------------------------------------------------------
function LifecyclePill({ status }: { status: LifecycleStatus }) {
  const labels: Record<LifecycleStatus, string> = {
    new: "New",
    confirmed: "Confirmed",
    dismissed: "Dismissed",
    watchlist: "Watchlist",
  };
  return (
    <span className="brand-caption text-foreground">{labels[status]}</span>
  );
}

// ---------------------------------------------------------------------------
// Date formatter: "DD MMM YYYY"
// ---------------------------------------------------------------------------
function fmtDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d
      .toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      })
      .replace(/\./g, "");
  } catch {
    return iso.slice(0, 10);
  }
}

// ---------------------------------------------------------------------------
// Actions Select (in-row lifecycle changer)
// ---------------------------------------------------------------------------
interface ActionsSelectProps {
  finding: EASMFinding;
  isObserver: boolean;
  onUpdate: (updated: EASMFinding) => void;
}

function ActionsSelect({ finding, isObserver, onUpdate }: ActionsSelectProps) {
  const [busy, setBusy] = useState(false);

  async function handleChange(newStatus: string) {
    if (busy) return;
    setBusy(true);
    try {
      const updated = await patchFindingLifecycle(
        finding.project_id,
        finding.id,
        newStatus as LifecycleStatus,
      );
      onUpdate(updated);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "error";
      toast.error(`Could not update finding. ${msg}`);
    } finally {
      setBusy(false);
    }
  }

  const trigger = (
    <SelectTrigger
      className="h-[44px] w-[130px]"
      disabled={isObserver || busy}
      aria-label="Lifecycle action"
    >
      <SelectValue placeholder={finding.lifecycle_status} />
    </SelectTrigger>
  );

  const select = (
    <Select
      value={finding.lifecycle_status}
      onValueChange={handleChange}
      disabled={isObserver || busy}
    >
      {isObserver ? (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>{trigger}</TooltipTrigger>
            <TooltipContent>
              Observers cannot modify finding status.
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : (
        trigger
      )}
      <SelectContent>
        <SelectItem value="confirmed">Confirm finding</SelectItem>
        <SelectItem value="dismissed">Dismiss (30 days)</SelectItem>
        <SelectItem value="watchlist">Watchlist</SelectItem>
        <SelectItem value="new">Reset to New</SelectItem>
      </SelectContent>
    </Select>
  );

  return select;
}

// ---------------------------------------------------------------------------
// FindingsTable
// ---------------------------------------------------------------------------
interface FindingsTableProps {
  findings: EASMFinding[];
  isObserver: boolean;
  onFindingUpdate: (updated: EASMFinding) => void;
}

export function FindingsTable({
  findings,
  isObserver,
  onFindingUpdate,
}: FindingsTableProps) {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-border bg-card text-left">
            <th
              className="py-2 px-3 brand-caption text-muted-foreground"
              style={{ width: "160px", minWidth: "160px" }}
            >
              Type
            </th>
            <th className="py-2 px-3 brand-caption text-muted-foreground flex-1">
              Target
            </th>
            <th
              className="py-2 px-3 brand-caption text-muted-foreground"
              style={{ width: "140px", minWidth: "140px" }}
            >
              Module
            </th>
            <th
              className="py-2 px-3 brand-caption text-muted-foreground"
              style={{ width: "100px", minWidth: "100px" }}
            >
              Severity
            </th>
            <th
              className="py-2 px-3 brand-caption text-muted-foreground"
              style={{ width: "120px", minWidth: "120px" }}
            >
              First seen
            </th>
            <th
              className="py-2 px-3 brand-caption text-muted-foreground"
              style={{ width: "120px", minWidth: "120px" }}
            >
              Last seen
            </th>
            <th
              className="py-2 px-3 brand-caption text-muted-foreground"
              style={{ width: "120px", minWidth: "120px" }}
            >
              Status
            </th>
            <th
              className="py-2 px-3 brand-caption text-muted-foreground"
              style={{ width: "140px", minWidth: "140px" }}
            >
              Actions
            </th>
          </tr>
        </thead>
        <tbody>
          {findings.map((finding) => {
            const isDismissed = finding.lifecycle_status === "dismissed";
            const isWatchlist = finding.lifecycle_status === "watchlist";
            const rowCls = [
              "border-b border-border/40 last:border-b-0",
              isDismissed ? "opacity-60 text-muted-foreground" : "",
            ]
              .filter(Boolean)
              .join(" ");

            // Target: truncate at 48 chars
            const target = finding.canonical_target;
            const truncatedTarget =
              target.length > 48 ? `${target.slice(0, 48)}…` : target;

            return (
              <tr key={finding.id} className={rowCls} style={{ height: "44px" }}>
                {/* Type */}
                <td
                  className="py-2 px-3 text-foreground text-sm"
                  style={{ width: "160px" }}
                >
                  {finding.bbot_event_type}
                </td>

                {/* Target — font-mono 12px */}
                <td className="py-2 px-3">
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span
                          className="font-mono text-[12px] text-foreground truncate block max-w-[300px]"
                          aria-label={target}
                        >
                          {truncatedTarget}
                        </span>
                      </TooltipTrigger>
                      {target.length > 48 && (
                        <TooltipContent className="font-mono text-xs max-w-[400px] break-all">
                          {target}
                        </TooltipContent>
                      )}
                    </Tooltip>
                  </TooltipProvider>
                </td>

                {/* Module */}
                <td
                  className="py-2 px-3 text-foreground text-sm"
                  style={{ width: "140px" }}
                >
                  {finding.module}
                </td>

                {/* Severity */}
                <td
                  className="py-2 px-3"
                  style={{ width: "100px" }}
                >
                  <SeverityChip severity={finding.severity} />
                </td>

                {/* First seen */}
                <td
                  className="py-2 px-3 text-foreground text-sm"
                  style={{ width: "120px" }}
                >
                  {fmtDate(finding.first_seen)}
                </td>

                {/* Last seen */}
                <td
                  className="py-2 px-3 text-foreground text-sm"
                  style={{ width: "120px" }}
                >
                  {fmtDate(finding.last_seen)}
                </td>

                {/* Status — lifecycle pill + watchlist dot */}
                <td
                  className="py-2 px-3"
                  style={{ width: "120px" }}
                >
                  <div className="flex items-center gap-1.5">
                    {isWatchlist && (
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span
                              className="w-2 h-2 rounded-full bg-[var(--brand-signal)] shrink-0"
                              aria-label="On watchlist"
                            />
                          </TooltipTrigger>
                          <TooltipContent>
                            On watchlist — will not be auto-dismissed
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    )}
                    <LifecyclePill status={finding.lifecycle_status} />
                  </div>
                </td>

                {/* Actions */}
                <td
                  className="py-2 px-3"
                  style={{ width: "140px" }}
                >
                  <ActionsSelect
                    finding={finding}
                    isObserver={isObserver}
                    onUpdate={onFindingUpdate}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
