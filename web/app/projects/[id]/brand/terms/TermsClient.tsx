"use client";

/**
 * TermsClient - (UI-SPEC §Surface 5).
 *
 * Owns:
 *   - Fetch of /brand/terms (with optional include_archived)
 *   - In-row mode Switch (PATCH /brand/terms/{id} {mode})
 *   - Archive Tooltip + window.confirm + PATCH {archived: true}
 *   - Show archived Switch
 *   - Empty state canonical copy
 *   - "Add brand term" button → BrandTermDialog (Surface 6)
 *   - Authority-matrix UI enforcement (Observer / Contributor-own-only archive)
 *
 * Role detection is prop-driven (mirrors 12-08 BrandDashboardClient). Plan 12-10
 * wires the real session-derived values. Defaults are safe (non-Observer,
 * non-Contributor) so stories / tests render the full authority set.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Loader2, Trash2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import type {
  BrandTermMode,
  BrandTermRead,
  BrandTermType,
} from "../lib/api";
import { listBrandTerms, patchBrandTerm } from "../lib/api";
import { BrandTermDialog } from "./BrandTermDialog";

// ---------------------------------------------------------------------------
// Format helpers
// ---------------------------------------------------------------------------

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso);
    const months = [
      "Jan","Feb","Mar","Apr","May","Jun",
      "Jul","Aug","Sep","Oct","Nov","Dec",
    ];
    const day = String(d.getUTCDate()).padStart(2, "0");
    return `${day} ${months[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
  } catch {
    return iso.slice(0, 10);
  }
}

function truncateSub(sub: string | null | undefined): string {
  if (!sub) return "-";
  return sub.length > 20 ? `${sub.slice(0, 20)}…` : sub;
}

// ---------------------------------------------------------------------------
// Chips
// ---------------------------------------------------------------------------

function TypeChip({ type }: { type: BrandTermType }) {
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-[12px] font-medium bg-muted text-muted-foreground">
      {type}
    </span>
  );
}

function ModeChip({ mode }: { mode: BrandTermMode }) {
  if (mode === "active") {
    return (
      <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-[12px] font-medium bg-teal-900/40 text-teal-300">
        Active
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-[12px] font-medium bg-muted text-muted-foreground">
      Watch-only
    </span>
  );
}

// ---------------------------------------------------------------------------
// Row-level mode Switch - optimistic flip + revert on error
// ---------------------------------------------------------------------------

interface ModeToggleProps {
  term: BrandTermRead;
  isObserver: boolean;
  onUpdate: (updated: BrandTermRead) => void;
}

function ModeToggle({ term, isObserver, onUpdate }: ModeToggleProps) {
  const [busy, setBusy] = useState(false);

  async function handleChange(nextChecked: boolean) {
    if (busy || isObserver) return;
    const previousMode: BrandTermMode = term.mode;
    const nextMode: BrandTermMode = nextChecked ? "active" : "watch_only";

    // Optimistic update
    onUpdate({ ...term, mode: nextMode });
    setBusy(true);
    try {
      const updated = await patchBrandTerm(term.project_id, term.id, {
        mode: nextMode,
      });
      onUpdate(updated);
    } catch {
      toast.error("Could not update scan mode. Try again.");
      onUpdate({ ...term, mode: previousMode });
    } finally {
      setBusy(false);
    }
  }

  const control = (
    <div className="flex items-center gap-2">
      {busy ? (
        <Loader2
          className="h-3 w-3 animate-spin text-muted-foreground"
          aria-label="Updating"
        />
      ) : (
        <ModeChip mode={term.mode} />
      )}
      <Switch
        checked={term.mode === "active"}
        onCheckedChange={handleChange}
        disabled={isObserver || busy}
        aria-label="Scan mode"
      />
    </div>
  );

  if (isObserver) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <span>{control}</span>
          </TooltipTrigger>
          <TooltipContent>
            Observers cannot toggle scan mode.
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }
  return control;
}

// ---------------------------------------------------------------------------
// Archive button - Tooltip + window.confirm + PATCH archived=true
// ---------------------------------------------------------------------------

interface ArchiveButtonProps {
  term: BrandTermRead;
  onUpdate: (updated: BrandTermRead) => void;
}

function ArchiveButton({ term, onUpdate }: ArchiveButtonProps) {
  const [busy, setBusy] = useState(false);

  async function handleClick() {
    if (busy) return;
    // Native confirm per UI-SPEC §Destructive Confirmations
    const ok = window.confirm(
      `Archive term '${term.value}'? Existing matches remain; scan cycle skips this term.`,
    );
    if (!ok) return;
    setBusy(true);
    try {
      const updated = await patchBrandTerm(term.project_id, term.id, {
        archived: true,
      });
      onUpdate(updated);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "error";
      toast.error(`Could not archive term. ${msg}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Archive term"
            className="text-muted-foreground hover:text-destructive"
            onClick={handleClick}
            disabled={busy}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Archive term</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// TermsClient
// ---------------------------------------------------------------------------

export interface TermsClientProps {
  projectId: string;
  /** Test-only - override session-role detection (plan 12-10 wires real value). */
  isObserver?: boolean;
  /** Project rank of current user - governs person-term radio gating (see dialog).
   *  Roles: "Admin" | "Analyst" | "Viewer" (global), and project rank integer.
   *  Exposed so plan 12-10 can wire session identity without refactor. */
  currentUserSub?: string;
  canCreatePerson?: boolean;
  canArchiveOthers?: boolean; // Lead/Admin/Analyst → true; Contributor → false
}

export function TermsClient({
  projectId,
  isObserver = false,
  currentUserSub,
  canCreatePerson = true,
  canArchiveOthers = true,
}: TermsClientProps) {
  const [terms, setTerms] = useState<BrandTermRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

  const fetchTerms = useCallback(
    async (includeArchived: boolean, signal: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const data = await listBrandTerms(projectId, includeArchived);
        if (!signal.aborted) setTerms(data);
      } catch (err) {
        if (!signal.aborted) {
          const msg = err instanceof Error ? err.message : "error";
          setError(`Could not load brand terms. ${msg}`);
        }
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    },
    [projectId],
  );

  useEffect(() => {
    const controller = new AbortController();
    fetchTerms(showArchived, controller.signal);
    return () => controller.abort();
  }, [fetchTerms, showArchived]);

  function handleTermUpdate(updated: BrandTermRead) {
    setTerms((prev) => {
      // If archived flag flipped true and we're not showing archived, drop
      if (updated.archived && !showArchived) {
        return prev.filter((t) => t.id !== updated.id);
      }
      return prev.map((t) => (t.id === updated.id ? { ...t, ...updated } : t));
    });
  }

  function handleTermCreated(t: BrandTermRead) {
    setTerms((prev) => [t, ...prev]);
  }

  // Split active + archived so archived render at bottom with opacity-60
  const active = terms.filter((t) => !t.archived);
  const archived = terms.filter((t) => t.archived);

  const canArchive = (term: BrandTermRead): boolean => {
    if (isObserver) return false;
    if (canArchiveOthers) return true;
    // Contributor: own only
    return term.created_by != null && term.created_by === currentUserSub;
  };

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        href={`/projects/${projectId}/brand`}
        className="inline-flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3 w-3" />
        Brand dashboard
      </Link>

      {/* Heading + primary CTA */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <h1
          className="font-medium leading-tight"
          style={{ fontSize: "32px" }}
        >
          Brand Terms
        </h1>
        {!isObserver && (
          <Button
            onClick={() => setDialogOpen(true)}
            style={{
              backgroundColor: "var(--brand-signal)",
              color: "var(--brand-ink)",
            }}
            className="font-medium hover:opacity-90"
          >
            Add brand term
          </Button>
        )}
      </div>

      {/* Show archived Switch (above table, left) */}
      <div className="flex items-center gap-2">
        <Switch
          id="show-archived"
          checked={showArchived}
          onCheckedChange={setShowArchived}
          aria-label="Show archived"
        />
        <label
          htmlFor="show-archived"
          className="text-[13px] text-muted-foreground cursor-pointer"
        >
          Show archived
        </label>
      </div>

      {/* Content - loading / error / empty / table */}
      {loading ? (
        <div className="rounded-md border border-border overflow-hidden">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-[44px] border-b border-border/40 last:border-b-0 bg-card/50 animate-pulse"
            />
          ))}
        </div>
      ) : error ? (
        <div className="flex items-center gap-3 py-6 text-destructive text-sm">
          <span>{error}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              const controller = new AbortController();
              fetchTerms(showArchived, controller.signal);
            }}
          >
            Retry
          </Button>
        </div>
      ) : active.length === 0 && archived.length === 0 ? (
        /* Empty state - UI-SPEC canonical copy */
        <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
          <h2 className="text-[22px] font-medium leading-[1.3]">
            No brand terms yet.
          </h2>
          <p className="text-muted-foreground max-w-md leading-[1.7]">
            Add a keyword, domain, product name, or person to start monitoring
            for brand mentions and lookalike domains.
          </p>
          {!isObserver && (
            <Button
              onClick={() => setDialogOpen(true)}
              style={{
                backgroundColor: "var(--brand-signal)",
                color: "var(--brand-ink)",
              }}
              className="font-medium hover:opacity-90"
            >
              Add brand term
            </Button>
          )}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-border bg-card text-left">
                <th className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground">
                  Value
                </th>
                <th
                  className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
                  style={{ width: "120px", minWidth: "120px" }}
                >
                  Type
                </th>
                <th
                  className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
                  style={{ width: "140px", minWidth: "140px" }}
                >
                  Mode
                </th>
                <th
                  className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground text-right"
                  style={{ width: "100px", minWidth: "100px" }}
                >
                  Matches 24h
                </th>
                <th
                  className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
                  style={{ width: "160px", minWidth: "160px" }}
                >
                  Created by
                </th>
                <th
                  className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
                  style={{ width: "140px", minWidth: "140px" }}
                >
                  Created at
                </th>
                <th
                  className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
                  style={{ width: "80px", minWidth: "80px" }}
                >
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {[...active, ...archived].map((term) => {
                const rowCls = [
                  "border-b border-border/40 last:border-b-0",
                  term.archived ? "opacity-60" : "",
                ]
                  .filter(Boolean)
                  .join(" ");
                return (
                  <tr
                    key={term.id}
                    className={rowCls}
                    style={{ height: "44px" }}
                    data-testid={`term-row-${term.id}`}
                  >
                    {/* Value */}
                    <td className="py-2 px-3">
                      <div className="flex items-center gap-2">
                        {term.high_noise_risk && (
                          <TooltipProvider>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <TriangleAlert
                                  className="h-3 w-3 text-orange-400 flex-shrink-0"
                                  aria-label="High noise risk"
                                />
                              </TooltipTrigger>
                              <TooltipContent>
                                Flagged high noise risk - term is in default
                                stoplist
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        )}
                        <span className="font-mono text-[12px] text-foreground">
                          {term.value}
                        </span>
                      </div>
                    </td>
                    {/* Type */}
                    <td className="py-2 px-3">
                      <TypeChip type={term.term_type} />
                    </td>
                    {/* Mode */}
                    <td className="py-2 px-3">
                      {term.archived ? (
                        <ModeChip mode={term.mode} />
                      ) : (
                        <ModeToggle
                          term={term}
                          isObserver={isObserver}
                          onUpdate={handleTermUpdate}
                        />
                      )}
                    </td>
                    {/* Matches 24h */}
                    <td className="py-2 px-3 text-right text-sm text-foreground">
                      {term.matches_24h == null ? "-" : term.matches_24h}
                    </td>
                    {/* Created by */}
                    <td className="py-2 px-3 text-sm">
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="font-mono text-[12px] text-muted-foreground">
                              {truncateSub(term.created_by)}
                            </span>
                          </TooltipTrigger>
                          <TooltipContent>
                            {term.created_by ?? "-"}
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </td>
                    {/* Created at */}
                    <td className="py-2 px-3 text-sm text-muted-foreground">
                      {fmtDate(term.created_at)}
                    </td>
                    {/* Actions */}
                    <td className="py-2 px-3">
                      {!term.archived && canArchive(term) && (
                        <ArchiveButton
                          term={term}
                          onUpdate={handleTermUpdate}
                        />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Add-brand-term dialog (Surface 6) */}
      <BrandTermDialog
        open={dialogOpen}
        projectId={projectId}
        canCreatePerson={canCreatePerson}
        onClose={() => setDialogOpen(false)}
        onCreated={(t) => {
          handleTermCreated(t);
          setDialogOpen(false);
        }}
      />
    </div>
  );
}
