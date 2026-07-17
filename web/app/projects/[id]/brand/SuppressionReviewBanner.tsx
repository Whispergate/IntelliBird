"use client";

/**
 * SuppressionReviewBanner — (UI-SPEC §Surface 3 + §Surface 4).
 *
 * Exports BOTH the amber banner and the review Dialog (single file).
 *
 * Banner: `border-l-4 border-[var(--brand-signal)] bg-accent/10` — identical
 * CSS to 24h-warning banner. Entire banner is clickable (role="button")
 * and opens the Dismissed-matches-expiring-soon Dialog.
 *
 * Dialog: shadcn <Dialog> with a ScrollArea of expiring dismissals. Each row
 * exposes 4 canonical actions: "Extend 30d", "Extend 90d", "Indefinite",
 * "Let resurface". Observer role: actions disabled + caption.
 */

import { useEffect, useState } from "react";
import { Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type {
  BrandSource,
  BrandSuppressionRow,
} from "./lib/api";
import { extendDismissal, listSuppressionReview } from "./lib/api";

// ---------------------------------------------------------------------------
// Source chip (local copy — colour rules identical to MatchTable SourceChip)
// ---------------------------------------------------------------------------
function SourceChip({ source }: { source: BrandSource }) {
  const labels: Record<BrandSource, string> = {
    dnstwist: "dnstwist",
    ct_log: "CT log",
    fts: "FTS",
  };
  const classes: Record<BrandSource, string> = {
    dnstwist: "bg-[var(--brand-signal)]/20 text-[var(--brand-signal)]",
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
// Relative-time formatter for "Expires: …"
// ---------------------------------------------------------------------------
function relExpires(iso: string): string {
  try {
    const diffMs = new Date(iso).getTime() - Date.now();
    if (diffMs <= 0) return "now";
    const m = Math.floor(diffMs / 60000);
    if (m < 60) return `in ${m}m`;
    const h = Math.floor(m / 60);
    if (h < 24) return `in ${h}h`;
    const d = Math.floor(h / 24);
    return `in ${d}d`;
  } catch {
    return iso.slice(0, 10);
  }
}

// ---------------------------------------------------------------------------
// SuppressionReviewBanner (default export)
// ---------------------------------------------------------------------------
export interface SuppressionReviewBannerProps {
  projectId: string;
  count: number;
  canEdit: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function SuppressionReviewBanner({
  projectId,
  count,
  canEdit,
  onOpenChange,
}: SuppressionReviewBannerProps) {
  const [open, setOpen] = useState(false);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    onOpenChange?.(next);
  }

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        onClick={() => handleOpenChange(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            handleOpenChange(true);
          }
        }}
        className="border-l-4 border-[var(--brand-signal)] bg-accent/10 px-4 py-3 rounded-sm cursor-pointer hover:bg-accent/20 transition-colors"
        aria-label="Review expiring dismissals"
      >
        <p className="text-sm text-foreground">
          {count} dismissed matches will re-surface in the next 7 days. Review
          before they return.
        </p>
      </div>

      <SuppressionReviewModal
        projectId={projectId}
        open={open}
        onOpenChange={handleOpenChange}
        canEdit={canEdit}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// SuppressionReviewModal (internal)
// ---------------------------------------------------------------------------
interface SuppressionReviewModalProps {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canEdit: boolean;
}

interface RowState extends BrandSuppressionRow {
  actioned?: boolean;
}

function SuppressionReviewModal({
  projectId,
  open,
  onOpenChange,
  canEdit,
}: SuppressionReviewModalProps) {
  const [rows, setRows] = useState<RowState[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Lazy-fetch on open
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    listSuppressionReview(projectId)
      .then((data) => {
        if (!cancelled) setRows(data.map((r) => ({ ...r, actioned: false })));
      })
      .catch(() => {
        if (!cancelled) setError("Could not load expiring dismissals.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, projectId]);

  async function applyAction(
    row: RowState,
    body: { extend_days?: number | null; let_resurface?: boolean },
  ) {
    if (busyId) return;
    setBusyId(row.id);
    try {
      await extendDismissal(projectId, row.id, body);
      setRows((prev) =>
        prev.map((r) => (r.id === row.id ? { ...r, actioned: true } : r)),
      );
    } catch {
      setError("Action failed. Please retry.");
    } finally {
      setBusyId(null);
    }
  }

  const remaining = rows.filter((r) => !r.actioned).length;
  const showEmptyState = !loading && !error && rows.length === 0;
  const showDrainedState =
    !loading && !error && rows.length > 0 && remaining === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Dismissed matches expiring soon</DialogTitle>
        </DialogHeader>
        <p className="text-base text-muted-foreground">
          These dismissed matches will re-surface within 7 days. Choose an
          action for each.
        </p>

        {!canEdit && (
          <p className="text-[12px] text-muted-foreground">
            Observers cannot modify dismissal windows.
          </p>
        )}

        {loading && (
          <div className="flex items-center justify-center py-12">
            <span className="text-sm text-muted-foreground">Loading…</span>
          </div>
        )}

        {error && (
          <div className="py-4 text-sm text-destructive">{error}</div>
        )}

        {(showEmptyState || showDrainedState) && (
          <div className="flex flex-col items-center gap-2 py-12 text-center">
            <h3 className="text-[22px] font-medium">
              No dismissals expiring soon.
            </h3>
            <p className="text-muted-foreground">
              All dismissed matches have a comfortable window remaining.
            </p>
          </div>
        )}

        {!loading && !error && rows.length > 0 && remaining > 0 && (
          <ScrollArea className="max-h-[400px] pr-3">
            <ul className="divide-y divide-border">
              {rows.map((row) => {
                const isActioned = !!row.actioned;
                return (
                  <li
                    key={row.id}
                    className={`flex items-center justify-between py-2 ${
                      isActioned ? "opacity-50" : ""
                    }`}
                  >
                    {/* Left */}
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span
                              className="font-mono text-[12px] text-foreground truncate max-w-[200px]"
                              aria-label={row.matched_value}
                            >
                              {row.matched_value.length > 40
                                ? `${row.matched_value.slice(0, 40)}…`
                                : row.matched_value}
                            </span>
                          </TooltipTrigger>
                          {row.matched_value.length > 40 && (
                            <TooltipContent className="font-mono text-xs max-w-[400px] break-all">
                              {row.matched_value}
                            </TooltipContent>
                          )}
                        </Tooltip>
                      </TooltipProvider>
                      <SourceChip source={row.match_source} />
                      <span className="text-[12px] text-muted-foreground">
                        Expires: {relExpires(row.dismiss_until)}
                      </span>
                    </div>

                    {/* Right — 4 canonical action buttons */}
                    {isActioned ? (
                      <Check
                        className="w-4 h-4 text-primary"
                        aria-label="Actioned"
                      />
                    ) : (
                      <div className="flex items-center gap-2 shrink-0">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={!canEdit || busyId === row.id}
                          onClick={() =>
                            applyAction(row, { extend_days: 30 })
                          }
                        >
                          Extend 30d
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={!canEdit || busyId === row.id}
                          onClick={() =>
                            applyAction(row, { extend_days: 90 })
                          }
                        >
                          Extend 90d
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={!canEdit || busyId === row.id}
                          onClick={() =>
                            applyAction(row, { extend_days: null })
                          }
                        >
                          Indefinite
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={!canEdit || busyId === row.id}
                          onClick={() =>
                            applyAction(row, { let_resurface: true })
                          }
                        >
                          Let resurface
                        </Button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </ScrollArea>
        )}

        <div className="flex justify-end pt-2">
          <Button variant="default" onClick={() => onOpenChange(false)}>
            Done
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
