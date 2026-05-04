"use client";

/**
 * AttachToCaseModal — Phase 31 Plan 07 (CASE-05).
 *
 * Reusable modal for attaching events or IOCs to an open case.
 *
 * Generalized interface:
 *   - eventIds: string[]  → calls attachEvents on confirm
 *   - iocIds: string[]    → calls attachIOCs on confirm
 * Exactly one of eventIds / iocIds should be provided and non-empty.
 */

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import {
  listCases,
  attachEvents,
  attachIOCs,
  type CaseRow,
} from "@/app/api-client";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AttachToCaseModalProps {
  projectId: string;
  eventIds?: string[];   // provide for events attach
  iocIds?: string[];     // provide for IOC attach
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void; // called after successful attach (to clear selection)
}

const SEVERITY_COLORS: Record<string, string> = {
  low: "bg-blue-500/20 text-blue-300",
  medium: "bg-yellow-500/20 text-yellow-300",
  high: "bg-orange-500/20 text-orange-300",
  critical: "bg-red-500/20 text-red-300",
};

// ---------------------------------------------------------------------------
// AttachToCaseModal
// ---------------------------------------------------------------------------

export function AttachToCaseModal({
  projectId,
  eventIds,
  iocIds,
  open,
  onOpenChange,
  onSuccess,
}: AttachToCaseModalProps) {
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const isIOCMode = (iocIds?.length ?? 0) > 0;
  const itemIds = isIOCMode ? (iocIds ?? []) : (eventIds ?? []);
  const itemCount = itemIds.length;

  // Load open cases when dialog opens
  useEffect(() => {
    if (!open) {
      setSelectedCaseId(null);
      setCases([]);
      return;
    }
    setLoading(true);
    listCases(projectId, { status: "open", limit: 50 })
      .then((res) => {
        setCases(res.items);
      })
      .catch((e: unknown) => {
        toast.error(`Failed to load cases: ${e instanceof Error ? e.message : String(e)}`);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [open, projectId]);

  async function handleConfirm() {
    if (!selectedCaseId || itemCount === 0) return;
    setSubmitting(true);
    try {
      if (isIOCMode) {
        await attachIOCs(projectId, selectedCaseId, itemIds);
        toast.success(`Attached ${itemCount} IOC${itemCount === 1 ? "" : "s"} to case`);
      } else {
        await attachEvents(projectId, selectedCaseId, itemIds);
        toast.success(`Attached ${itemCount} event${itemCount === 1 ? "" : "s"} to case`);
      }
      onSuccess();
      onOpenChange(false);
    } catch (e: unknown) {
      toast.error(`Failed to attach: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Attach to Case</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Select an open case to attach {itemCount} {isIOCMode ? "IOC" : "event"}{itemCount === 1 ? "" : "s"} to:
          </p>

          {loading ? (
            <div className="flex justify-center py-6">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : cases.length === 0 ? (
            <p className="text-sm text-muted-foreground italic py-4">
              No open cases — create one first from the Cases tab.
            </p>
          ) : (
            <div className="border rounded-md divide-y max-h-72 overflow-y-auto">
              {cases.map((c) => (
                <label
                  key={c.id}
                  className={`flex items-center gap-3 px-3 py-3 cursor-pointer hover:bg-muted/50 ${
                    selectedCaseId === c.id ? "bg-muted/40" : ""
                  }`}
                >
                  <input
                    type="radio"
                    name="case-select"
                    value={c.id}
                    checked={selectedCaseId === c.id}
                    onChange={() => setSelectedCaseId(c.id)}
                    className="h-4 w-4"
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{c.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {c.severity ? (
                        <Badge className={`text-[10px] uppercase font-mono ${SEVERITY_COLORS[c.severity] ?? ""}`}>
                          {c.severity}
                        </Badge>
                      ) : (
                        <span>No severity</span>
                      )}
                    </p>
                  </div>
                </label>
              ))}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleConfirm()}
            disabled={!selectedCaseId || submitting || cases.length === 0}
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            Attach
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
