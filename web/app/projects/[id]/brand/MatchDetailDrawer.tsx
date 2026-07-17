"use client";

/**
 * MatchDetailDrawer — (BRAND-02).
 *
 * shadcn Sheet (right side, sm:max-w-xl) with three sections:
 *   1. Provenance  — 4-row dl (Detector badge / Raw input / Matched value / Similarity)
 *   2. History     — aggregate count badges + last-10 timeline (reverse-chrono)
 *   3. Actions     — Confirm / Dismiss / Watchlist + optional Note textarea (Lead+)
 *                    Footer hidden for Observer role (via useProjectRole).
 *
 * Props pattern: details passed in (fetched by parent BrandDashboardClient on
 * `?match=<uuid>` param change). Parent re-fetches after each action.
 *
 * After-action: drawer stays open. onUpdate() triggers MatchTable row refresh.
 */

import { useState } from "react";
import { toast } from "sonner";

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import { useProjectRole } from "@/app/projects/[id]/ProjectRoleProvider";
import type {
  BrandMatchRead,
  BrandLifecycleStatus,
  BrandSource,
  MatchDetailsResponse,
  HistoryEntry,
  AggregateCounts,
} from "./lib/api";
import { patchBrandMatch, fetchBrandMatchDetails } from "./lib/api";

// ---------------------------------------------------------------------------
// DetectorBadge — mirrors SourceChip colour map from MatchTable.tsx
// ---------------------------------------------------------------------------
function DetectorBadge({ source }: { source: BrandSource | string }) {
  const labels: Record<string, string> = {
    dnstwist: "dnstwist",
    ct_log: "CT log",
    fts: "FTS",
  };
  const classes: Record<string, string> = {
    dnstwist: "bg-[var(--brand-signal)]/20 text-[var(--brand-signal)]",
    ct_log: "bg-teal-900/40 text-teal-300",
    fts: "bg-muted text-muted-foreground",
  };
  const label = labels[source] ?? source;
  const cls = classes[source] ?? "bg-muted text-muted-foreground";
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-sm text-[12px] font-medium ${cls}`}
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// AggregateBadge
// ---------------------------------------------------------------------------
function AggregateBadge({
  label,
  count,
  colorClass,
}: {
  label: string;
  count: number;
  colorClass: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-sm border px-1.5 py-px brand-caption ${colorClass}`}
    >
      {label} {count}x
    </span>
  );
}

// ---------------------------------------------------------------------------
// History helpers
// ---------------------------------------------------------------------------
function formatAbsoluteDate(iso: string): string {
  try {
    const d = new Date(iso);
    const yyyy = d.getUTCFullYear();
    const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(d.getUTCDate()).padStart(2, "0");
    const hh = String(d.getUTCHours()).padStart(2, "0");
    const min = String(d.getUTCMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
  } catch {
    return iso;
  }
}

const ACTION_LABEL: Record<string, string> = {
  confirmed: "confirmed",
  dismissed: "dismissed",
  watchlist: "watchlisted",
  new: "reset to new",
};

const ACTION_COLOUR: Record<string, string> = {
  confirmed: "text-green-300",
  dismissed: "text-muted-foreground",
  watchlist: "text-[var(--brand-signal)]",
  new: "text-foreground",
};

function actionLabel(action: string): string {
  return ACTION_LABEL[action] ?? action;
}

function actionColour(action: string): string {
  return ACTION_COLOUR[action] ?? "text-foreground";
}

// ---------------------------------------------------------------------------
// TimelineEntry
// ---------------------------------------------------------------------------
function TimelineEntry({ entry }: { entry: HistoryEntry }) {
  return (
    <div className="flex flex-col gap-0.5 py-2 border-b border-border/40 last:border-b-0">
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="brand-caption text-muted-foreground font-mono">
          [{formatAbsoluteDate(entry.acted_at)}]
        </span>
        <span className="brand-caption text-muted-foreground">
          {entry.actor_email ?? entry.actor_id}
        </span>
        <span className={`brand-caption font-medium ${actionColour(entry.action)}`}>
          {actionLabel(entry.action)}
        </span>
        {entry.matched_value && entry.match_id && (
          <a
            href={`?match=${entry.match_id}`}
            className="brand-caption text-muted-foreground/60 hover:text-foreground hover:underline font-mono truncate max-w-[120px]"
          >
            {entry.matched_value}
          </a>
        )}
      </div>
      {entry.note && (
        <p className="text-[12px] text-muted-foreground pl-2 italic">
          {entry.note}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MatchDetailDrawer
// ---------------------------------------------------------------------------
export interface MatchDetailDrawerProps {
  projectId: string;
  match: BrandMatchRead;
  details: MatchDetailsResponse;
  open: boolean;
  onClose: () => void;
  onUpdate: (updated: BrandMatchRead) => void;
}

export function MatchDetailDrawer({
  projectId,
  match,
  details: initialDetails,
  open,
  onClose,
  onUpdate,
}: MatchDetailDrawerProps) {
  const { isObserver } = useProjectRole();
  const [details, setDetails] = useState<MatchDetailsResponse>(initialDetails);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleAction(action: BrandLifecycleStatus) {
    if (busy) return;
    setBusy(true);
    try {
      const body: { lifecycle_status: BrandLifecycleStatus; note?: string } = {
        lifecycle_status: action,
      };
      if (note.trim()) body.note = note.trim();

      const updated = await patchBrandMatch(projectId, match.id, body);

      // Refetch details to update history + aggregate counts
      try {
        const refreshed = await fetchBrandMatchDetails(projectId, match.id);
        setDetails(refreshed);
      } catch {
        // Non-fatal — details may be stale but action succeeded
      }

      setNote("");
      onUpdate(updated);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "error";
      toast.error(`Could not update match. ${msg}`);
    } finally {
      setBusy(false);
    }
  }

  const { provenance, aggregate_counts, timeline } = details;

  const noteWarning = note.length >= 490;

  return (
    <Sheet
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <SheetContent
        side="right"
        className="sm:max-w-xl flex flex-col p-0 overflow-y-auto"
        data-testid="match-detail-drawer"
      >
        {/* Header */}
        <SheetHeader className="px-6 pt-6 pb-4 border-b border-border shrink-0">
          <SheetTitle>Match detail</SheetTitle>
        </SheetHeader>

        {/* Provenance section */}
        <div className="px-6 py-4 border-b border-border bg-card/40 rounded-md mx-4 mt-4 mb-4 shrink-0">
          <h3 className="brand-caption text-muted-foreground uppercase mb-3">
            Provenance
          </h3>
          <dl className="grid grid-cols-[120px_1fr] gap-y-3 gap-x-4">
            <dt className="brand-caption text-muted-foreground self-start pt-0.5">
              Detector
            </dt>
            <dd>
              <DetectorBadge source={provenance.detector} />
            </dd>

            <dt className="brand-caption text-muted-foreground self-start pt-0.5">
              Raw input
            </dt>
            <dd className="font-mono text-[12px] text-foreground break-all">
              {provenance.raw_input ?? "—"}
            </dd>

            <dt className="brand-caption text-muted-foreground self-start pt-0.5">
              Matched value
            </dt>
            <dd className="font-mono text-[12px] text-foreground break-all">
              {provenance.matched_value}
            </dd>

            <dt className="brand-caption text-muted-foreground self-start pt-0.5">
              Similarity
            </dt>
            <dd className="font-mono text-[12px] text-foreground">
              {provenance.similarity != null
                ? `${(provenance.similarity * 100).toFixed(0)}%`
                : "—"}
            </dd>
          </dl>
        </div>

        {/* History section */}
        <div className="px-6 py-4 flex-1 overflow-y-auto">
          <h3 className="brand-caption text-muted-foreground uppercase mb-3">
            History
          </h3>

          {/* Aggregate counts */}
          <AggregateCounts counts={aggregate_counts} />

          {/* Timeline */}
          <div className="mt-2">
            {timeline.length === 0 ? (
              <p className="text-[12px] text-muted-foreground py-4">
                No prior actions recorded.
              </p>
            ) : (
              timeline.map((entry, i) => (
                <TimelineEntry key={`${entry.match_id ?? i}-${entry.acted_at}`} entry={entry} />
              ))
            )}
          </div>
        </div>

        {/* Actions footer — hidden for Observer */}
        {!isObserver && (
          <div className="sticky bottom-0 bg-background border-t border-border px-6 py-4 space-y-3 shrink-0">
            {/* Note textarea */}
            <div className="space-y-1.5">
              <Label htmlFor="match-note" className="text-sm">
                Note (optional)
              </Label>
              <Textarea
                id="match-note"
                placeholder="Add a note to this action…"
                maxLength={500}
                rows={3}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="resize-none text-sm"
                disabled={busy}
              />
              <p
                className={`text-[12px] text-right ${
                  noteWarning ? "text-destructive" : "text-muted-foreground"
                }`}
              >
                {note.length}/500
              </p>
            </div>

            {/* Action buttons */}
            <div className="flex items-center gap-2 flex-wrap">
              <Button
                size="sm"
                variant="default"
                onClick={() => handleAction("confirmed")}
                disabled={busy}
              >
                Confirm
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleAction("dismissed")}
                disabled={busy}
              >
                Dismiss
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleAction("watchlist")}
                disabled={busy}
              >
                Watchlist
              </Button>
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

// ---------------------------------------------------------------------------
// AggregateCounts sub-component (named to avoid clash with type import)
// ---------------------------------------------------------------------------
function AggregateCounts({ counts }: { counts: AggregateCounts }) {
  return (
    <div className="flex items-center gap-2 mb-4 flex-wrap">
      <AggregateBadge
        label="Confirmed"
        count={counts.confirmed}
        colorClass="bg-green-500/15 text-green-300 border-green-700"
      />
      <AggregateBadge
        label="Dismissed"
        count={counts.dismissed}
        colorClass="bg-muted text-muted-foreground border-border"
      />
      <AggregateBadge
        label="Watchlist"
        count={counts.watchlist}
        colorClass="bg-[var(--brand-signal)]/15 text-[var(--brand-signal)] border-[var(--brand-signal)]/40"
      />
      <AggregateBadge
        label="New"
        count={counts.new}
        colorClass="bg-card text-foreground border-border"
      />
    </div>
  );
}
