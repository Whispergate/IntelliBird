"use client";

/**
 * MatchTable — Phase 12 plan 12-08 (UI-SPEC §Surface 2 §Match table).
 *
 * 8-column brand-match table per UI-SPEC:
 *   Term (180px) | Matched value (flex-1, font-mono 12px, truncate@48) |
 *   Source (120px chip) | Severity (100px chip) |
 *   First seen (120px) | Last seen (120px) |
 *   Status (140px pill + signal-amber dot on watchlist) | Actions (140px Select)
 *
 * Row height 44px (WCAG 2.5.5 — matches Phase 11 FindingsTable).
 * Dismissed rows: opacity-60 + text-muted-foreground.
 * Watchlist rows: signal-amber dot before lifecycle pill.
 * Observer role: Actions Select disabled with tooltip
 *   "Observers cannot modify match status."
 */

import { useState } from "react";
import { TriangleAlert } from "lucide-react";
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
import type {
  BrandLifecycleStatus,
  BrandMatchRead,
  BrandSeverity,
  BrandSource,
  BrandTermType,
} from "./lib/api";
import { patchBrandMatch } from "./lib/api";

// ---------------------------------------------------------------------------
// Source chip — UI-SPEC §Color
//   dnstwist: signal-amber (accent reserved #5)
//   ct_log:   teal mist
//   fts:      slate muted
// ---------------------------------------------------------------------------
function SourceChip({ source }: { source: BrandSource }) {
  const labels: Record<BrandSource, string> = {
    dnstwist: "dnstwist",
    ct_log: "CT log",
    fts: "FTS",
  };
  const classes: Record<BrandSource, string> = {
    dnstwist:
      "bg-[var(--brand-signal)]/20 text-[var(--brand-signal)]",
    ct_log: "bg-teal-900/40 text-teal-300",
    fts: "bg-muted text-muted-foreground",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-sm text-[12px] font-medium ${classes[source]}`}
    >
      {labels[source]}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Severity chip — UI-SPEC §Color
// ---------------------------------------------------------------------------
function SeverityChip({ severity }: { severity: BrandSeverity }) {
  const classes: Record<BrandSeverity, string> = {
    high: "bg-destructive/20 text-destructive",
    medium: "bg-orange-500/20 text-orange-300",
    low: "bg-muted text-muted-foreground",
  };
  const labels: Record<BrandSeverity, string> = {
    high: "HIGH",
    medium: "MEDIUM",
    low: "LOW",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-sm text-[12px] font-medium ${classes[severity]}`}
    >
      {labels[severity]}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Term-type chip
// ---------------------------------------------------------------------------
function TermTypeChip({ type }: { type: BrandTermType }) {
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-[12px] font-medium bg-muted text-muted-foreground">
      {type}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Lifecycle pill
// ---------------------------------------------------------------------------
function LifecyclePill({
  status,
  dismissUntil,
}: {
  status: BrandLifecycleStatus;
  dismissUntil: string | null;
}) {
  let label = "";
  switch (status) {
    case "new":
      label = "New";
      break;
    case "confirmed":
      label = "Confirmed";
      break;
    case "watchlist":
      label = "Watchlist";
      break;
    case "dismissed": {
      if (dismissUntil) {
        const days = Math.max(
          1,
          Math.ceil(
            (new Date(dismissUntil).getTime() - Date.now()) /
              (24 * 60 * 60 * 1000),
          ),
        );
        label = `Dismissed-${days}d`;
      } else {
        label = "Dismissed";
      }
      break;
    }
  }
  return (
    <span className="text-[12px] font-medium text-foreground">{label}</span>
  );
}

// ---------------------------------------------------------------------------
// Relative time formatter
// ---------------------------------------------------------------------------
function relTime(iso: string): string {
  try {
    const ts = new Date(iso).getTime();
    const diffMs = Date.now() - ts;
    const m = Math.floor(diffMs / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    return `${d}d ago`;
  } catch {
    return iso.slice(0, 10);
  }
}

// ---------------------------------------------------------------------------
// Actions Select — in-row lifecycle changer
// ---------------------------------------------------------------------------
interface ActionsSelectProps {
  match: BrandMatchRead;
  isObserver: boolean;
  onUpdate: (updated: BrandMatchRead) => void;
}

function ActionsSelect({ match, isObserver, onUpdate }: ActionsSelectProps) {
  const [busy, setBusy] = useState(false);

  async function handleChange(optionValue: string) {
    if (busy) return;
    setBusy(true);
    try {
      let body:
        | { lifecycle_status: BrandLifecycleStatus; dismiss_days?: number }
        | null = null;
      switch (optionValue) {
        case "confirm":
          body = { lifecycle_status: "confirmed" };
          break;
        case "dismiss30":
          body = { lifecycle_status: "dismissed", dismiss_days: 30 };
          break;
        case "watchlist":
          body = { lifecycle_status: "watchlist" };
          break;
        case "reset":
          body = { lifecycle_status: "new" };
          break;
      }
      if (!body) return;
      const updated = await patchBrandMatch(match.project_id, match.id, body);
      onUpdate(updated);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "error";
      toast.error(`Could not update match. ${msg}`);
    } finally {
      setBusy(false);
    }
  }

  const trigger = (
    <SelectTrigger
      className="h-[44px] w-[140px]"
      disabled={isObserver || busy}
      aria-label="Lifecycle action"
    >
      <SelectValue placeholder={match.lifecycle_status} />
    </SelectTrigger>
  );

  return (
    <Select onValueChange={handleChange} disabled={isObserver || busy}>
      {isObserver ? (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>{trigger}</TooltipTrigger>
            <TooltipContent>
              Observers cannot modify match status.
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : (
        trigger
      )}
      <SelectContent>
        <SelectItem value="confirm">Confirm match</SelectItem>
        <SelectItem value="dismiss30">Dismiss (30 days)</SelectItem>
        <SelectItem value="watchlist">Watchlist</SelectItem>
        <SelectItem value="reset">Reset to New</SelectItem>
      </SelectContent>
    </Select>
  );
}

// ---------------------------------------------------------------------------
// MatchTable
// ---------------------------------------------------------------------------
interface MatchTableProps {
  matches: BrandMatchRead[];
  isObserver: boolean;
  onMatchUpdate: (updated: BrandMatchRead) => void;
  /** Called with match.id when the matched_value cell is clicked. */
  onMatchClick?: (matchId: string) => void;
  /** Highlights the row whose id matches this value (from ?match= URL param). */
  activeMatchId?: string | null;
}

export function MatchTable({
  matches,
  isObserver,
  onMatchUpdate,
  onMatchClick,
  activeMatchId,
}: MatchTableProps) {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-border bg-card text-left">
            <th
              className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
              style={{ width: "180px", minWidth: "180px" }}
            >
              Term
            </th>
            <th className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground">
              Matched value
            </th>
            <th
              className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
              style={{ width: "120px", minWidth: "120px" }}
            >
              Source
            </th>
            <th
              className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
              style={{ width: "100px", minWidth: "100px" }}
            >
              Severity
            </th>
            <th
              className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
              style={{ width: "120px", minWidth: "120px" }}
            >
              First seen
            </th>
            <th
              className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
              style={{ width: "120px", minWidth: "120px" }}
            >
              Last seen
            </th>
            <th
              className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
              style={{ width: "140px", minWidth: "140px" }}
            >
              Status
            </th>
            <th
              className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
              style={{ width: "140px", minWidth: "140px" }}
            >
              Actions
            </th>
          </tr>
        </thead>
        <tbody>
          {matches.map((match) => {
            const isDismissed = match.lifecycle_status === "dismissed";
            const isWatchlist = match.lifecycle_status === "watchlist";
            const isActive = match.id === activeMatchId;
            const rowCls = [
              "border-b border-border/40 last:border-b-0",
              isDismissed ? "opacity-60 text-muted-foreground" : "",
              isActive ? "bg-card/60" : "",
            ]
              .filter(Boolean)
              .join(" ");

            const termValue = match.term?.value ?? match.term_value ?? "—";
            const termType = match.term?.term_type ?? match.term_type ?? null;
            const highNoiseRisk =
              match.term?.high_noise_risk ?? match.high_noise_risk ?? false;

            const raw = match.matched_value;
            const truncated = raw.length > 48 ? `${raw.slice(0, 48)}…` : raw;

            return (
              <tr
                key={match.id}
                className={rowCls}
                style={{ height: "44px" }}
              >
                {/* Term */}
                <td
                  className="py-2 px-3 text-foreground text-sm"
                  style={{ width: "180px" }}
                >
                  <div className="flex items-center gap-1.5">
                    {highNoiseRisk && (
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <TriangleAlert
                              className="w-3 h-3 text-[var(--brand-signal)] shrink-0"
                              aria-label="High noise risk"
                            />
                          </TooltipTrigger>
                          <TooltipContent>
                            Flagged high noise risk — term is in default stoplist
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    )}
                    <span className="truncate">{termValue}</span>
                    {termType && <TermTypeChip type={termType} />}
                  </div>
                </td>

                {/* Matched value — font-mono 12px + click affordance (UI-SPEC §Surface 3) */}
                <td className="py-2 px-3">
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span
                          className="font-mono text-[12px] text-foreground truncate block max-w-[360px] cursor-pointer hover:underline decoration-[var(--brand-signal)] underline-offset-2"
                          aria-label={raw}
                          onClick={() => onMatchClick?.(match.id)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) =>
                            (e.key === "Enter" || e.key === " ") &&
                            onMatchClick?.(match.id)
                          }
                        >
                          {truncated}
                        </span>
                      </TooltipTrigger>
                      {raw.length > 48 && (
                        <TooltipContent className="font-mono text-xs max-w-[400px] break-all">
                          {raw}
                        </TooltipContent>
                      )}
                    </Tooltip>
                  </TooltipProvider>
                </td>

                {/* Source */}
                <td className="py-2 px-3" style={{ width: "120px" }}>
                  <SourceChip source={match.match_source} />
                </td>

                {/* Severity */}
                <td className="py-2 px-3" style={{ width: "100px" }}>
                  <SeverityChip severity={match.severity} />
                </td>

                {/* First seen */}
                <td
                  className="py-2 px-3 text-foreground text-sm"
                  style={{ width: "120px" }}
                >
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span>{relTime(match.first_seen)}</span>
                      </TooltipTrigger>
                      <TooltipContent>{match.first_seen}</TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </td>

                {/* Last seen */}
                <td
                  className="py-2 px-3 text-foreground text-sm"
                  style={{ width: "120px" }}
                >
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span>{relTime(match.last_seen)}</span>
                      </TooltipTrigger>
                      <TooltipContent>{match.last_seen}</TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </td>

                {/* Status — lifecycle pill + watchlist signal-amber dot */}
                <td className="py-2 px-3" style={{ width: "140px" }}>
                  <div className="flex items-center gap-1.5">
                    {isWatchlist && (
                      <span
                        className="w-2 h-2 rounded-full bg-[var(--brand-signal)] shrink-0"
                        aria-label="On watchlist"
                        data-testid="watchlist-dot"
                      />
                    )}
                    <LifecyclePill
                      status={match.lifecycle_status}
                      dismissUntil={match.dismiss_until}
                    />
                  </div>
                </td>

                {/* Actions */}
                <td className="py-2 px-3" style={{ width: "140px" }}>
                  <ActionsSelect
                    match={match}
                    isObserver={isObserver}
                    onUpdate={onMatchUpdate}
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
