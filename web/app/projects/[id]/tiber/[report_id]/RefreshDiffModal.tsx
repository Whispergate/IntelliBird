"use client";

/**
 * RefreshDiffModal - Surface 5: Refresh from project data diff modal.
 * UI-SPEC §Surface 5 verbatim.
 *
 * Opens when "Refresh from project data" is clicked on a section.
 * Fetches diff rows, shows 2-column accept/reject grid.
 * "Apply accepted ({N} selected)" fires PATCH with accepted_field_paths only.
 * "Keep current data" closes without action.
 */

import { useEffect, useState } from "react";
import { ArrowRight, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";

import {
  applySectionRefresh,
  refreshSection,
  type RefreshDiffRow,
  type TiberReport,
} from "../lib/api";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

type SectionKey = "actionable_intelligence" | "threat_landscape" | "actor_profiles" | "scenarios";

interface RefreshDiffModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  reportId: string;
  section: SectionKey;
  onApplied: (updatedReport: TiberReport) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function RefreshDiffModal({
  open,
  onOpenChange,
  projectId,
  reportId,
  section,
  onApplied,
}: RefreshDiffModalProps) {
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [rows, setRows] = useState<RefreshDiffRow[]>([]);
  const [accepted, setAccepted] = useState<Set<string>>(new Set());

  // Fetch diff when modal opens
  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setRows([]);
    setAccepted(new Set());
    refreshSection({ projectId, reportId, section })
      .then((diff) => {
        setRows(diff.rows);
      })
      .catch((e) => {
        toast.error(`Could not load refresh diff. ${e instanceof Error ? e.message : String(e)}`);
        onOpenChange(false);
      })
      .finally(() => setLoading(false));
  }, [open, projectId, reportId, section]);

  function toggleAccept(fieldPath: string, checked: boolean) {
    setAccepted((prev) => {
      const next = new Set(prev);
      if (checked) next.add(fieldPath);
      else next.delete(fieldPath);
      return next;
    });
  }

  function acceptAll() {
    setAccepted(new Set(rows.map((r) => r.field_path)));
  }

  function skipAll() {
    setAccepted(new Set());
  }

  async function handleApply() {
    const acceptedFieldPaths = Array.from(accepted);
    if (acceptedFieldPaths.length === 0) return;
    setApplying(true);
    try {
      const updatedReport = await applySectionRefresh({
        projectId,
        reportId,
        section,
        acceptedFieldPaths,
      });
      toast.success(`Section updated with ${acceptedFieldPaths.length} changes.`);
      onApplied(updatedReport);
      onOpenChange(false);
    } catch (e) {
      toast.error(`Could not apply refresh. ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setApplying(false);
    }
  }

  const acceptedCount = accepted.size;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Refresh from project data</DialogTitle>
          <DialogDescription>
            Review changes before applying. Accept or skip each update.
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4">
          {/* Bulk actions */}
          {!loading && rows.length > 0 && (
            <div className="flex gap-2 mb-4">
              <Button variant="ghost" size="sm" onClick={acceptAll}>
                Accept all
              </Button>
              <Button variant="ghost" size="sm" onClick={skipAll}>
                Skip all
              </Button>
            </div>
          )}

          {/* Column headers */}
          {!loading && rows.length > 0 && (
            <div className="grid grid-cols-[1fr_auto_1fr] gap-4 mb-2">
              <span className="brand-caption text-muted-foreground">Current</span>
              <span />
              <span className="brand-caption text-muted-foreground">New from project data</span>
            </div>
          )}

          {/* Loading skeleton */}
          {loading && (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-10 w-full rounded-md bg-muted animate-pulse" />
              ))}
            </div>
          )}

          {/* Empty state */}
          {!loading && rows.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-6">
              No changes detected from project data.
            </p>
          )}

          {/* Diff rows - UI-SPEC §Surface 5 verbatim grid layout */}
          {!loading && (
            <div className="max-h-[400px] overflow-y-auto">
              {rows.map((row, i) => {
                const isAccepted = accepted.has(row.field_path);
                const currentDisplay =
                  row.current_value !== null && row.current_value !== undefined
                    ? String(row.current_value)
                    : null;
                const newDisplay =
                  row.new_value !== null && row.new_value !== undefined
                    ? String(row.new_value)
                    : null;

                return (
                  <div
                    key={row.field_path}
                    className="grid grid-cols-[1fr_auto_1fr] gap-4 items-start py-2 border-b border-border"
                  >
                    <div className="text-sm">
                      {currentDisplay ?? (
                        <span className="text-muted-foreground italic">- empty -</span>
                      )}
                      <p className="text-xs text-muted-foreground/60 mt-0.5 brand-mono">
                        {row.field_path}
                      </p>
                    </div>
                    <div className="flex items-center gap-1 pt-0.5">
                      <Checkbox
                        id={`accept-${i}`}
                        checked={isAccepted}
                        onCheckedChange={(checked) =>
                          toggleAccept(row.field_path, checked === true)
                        }
                      />
                      <Label htmlFor={`accept-${i}`} className="text-xs text-muted-foreground sr-only">
                        Accept this change
                      </Label>
                      <ArrowRight size={12} className="text-muted-foreground/40" />
                    </div>
                    <div className="text-sm">
                      {newDisplay ?? (
                        <span className="text-muted-foreground italic">- empty -</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <DialogFooter className="mt-4 flex items-center gap-2">
          <Button
            variant="default"
            onClick={handleApply}
            disabled={acceptedCount === 0 || applying}
          >
            {applying ? (
              <>
                <Loader2 size={14} className="animate-spin mr-1" />
                Applying…
              </>
            ) : (
              `Apply accepted (${acceptedCount} selected)`
            )}
          </Button>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={applying}>
            Keep current data
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
