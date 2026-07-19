"use client";

/**
 * ExportDialog - PRJ-07 per-project export surface.
 *
 * UI-SPEC §Export flow PRJ-07 locks:
 *   - RadioGroup: "STIX 2.1 Bundle (.stix.json)" / "CSV (.csv)"
 *   - Optional date-range inputs (two native <input type="date">, matching v1.5
 *     /events date pattern)
 *   - Primary CTA "Export" in signal amber
 *   - On submit: POST /api/projects/{id}/export?format=X → response streamed
 *     as a Blob; browser triggers download via Object URL + <a download>
 *   - On 413: toast.error with the EXACT UI-SPEC copy
 *     "Export exceeds 50,000 event cap - narrow the date range or scope and
 *     retry."
 *   - On success: toast "Export ready: <filename>" + close dialog
 *
 * Filename convention (UI-SPEC §Export flow):
 *   Backend is the SOLE source of truth. Plan 10-08 locked exportProject() to
 *   return `{ blob, filename }` by parsing the Content-Disposition response
 *   header. We destructure and use `filename` directly - NEVER re-slug
 *   project.name client-side. A client-side slug() helper here would create
 *   silent drift if backend slug rules ever change (e.g., transliteration,
 *   length cap, Unicode normalisation). The backend-authoritative filename
 *   pattern is `intellibird-project-<slug>-<YYYY-MM-DD>.<ext>`; see
 *   web/app/projects/lib/api.ts parseContentDispositionFilename for the
 *   Content-Disposition parser (handles RFC 5987 + quoted + bare forms).
 *
 * Observer role gating (UI-SPEC §Export flow + plan context):
 * simplification: the Export button in OverviewClient is shown
 *   regardless of project role; backend returns 403 if the caller lacks
 *   export permission. Dialog surfaces the 403 as a toast. Full client-side
 *   hide-for-Observer behaviour is a v2.1 follow-up once the frontend has a
 *   ready path to a project-role prop threaded from the JWT claim. UI-SPEC
 *   notes "defence-in-depth" - the backend 403 is authoritative.
 *
 * Date range is currently advisory - plan 10-07 shipped the export endpoint
 * with a 50k event hard cap and no per-range narrowing. The date inputs are
 * included to lock the UI shape for when the cap becomes tighter
 * for now the dialog prints a small note explaining this.
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";

import type { ProjectResponse } from "../../lib/api";
import { exportProject } from "../../lib/api";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

// NOTE: no client-side slug() helper. Backend is the sole source of truth for
// the export filename (intellibird-project-<slug>-<date>.<ext>). exportProject()
// returns {blob, filename} by parsing the Content-Disposition response header
// - see web/app/projects/lib/api.ts. Duplicating the slug regex here would
// create silent drift if backend rules ever change.

type Format = "stix" | "csv";

export function ExportDialog({
  project,
  open,
  onClose,
}: {
  project: ProjectResponse;
  open: boolean;
  onClose: () => void;
}) {
  const [format, setFormat] = useState<Format>("stix");
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");
  const [busy, setBusy] = useState(false);

  // Reset form when the dialog opens - matches ProjectDialog / MembershipDialog
  // reset-on-open convention from plans 10-08 + 10-11 Task 1.
  useEffect(() => {
    if (open) {
      setFormat("stix");
      setFromDate("");
      setToDate("");
      setBusy(false);
    }
  }, [open]);

  async function submit() {
    setBusy(true);
    try {
      const { blob, filename } = await exportProject(project.id, format);
      // Trigger download. Uses an anchor+click rather than window.location
      // because Firefox ignores `download` attribute on navigation-style
      // downloads for same-origin URLs with custom extensions.
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success(`Export ready: ${filename}`);
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Export failed.";
      const status =
        err && typeof err === "object" && "status" in err
          ? (err as { status?: number }).status
          : undefined;

      // 413 detection: either HTTP status or detail string. Backend sends
      // detail "exceeds 50,000 event cap" per plan 10-07.
      if (
        status === 413 ||
        msg.includes("50,000") ||
        msg.includes("50000") ||
        msg.toLowerCase().includes("event cap") ||
        msg.toLowerCase().includes("export_too_large")
      ) {
        toast.error(
          "Export exceeds 50,000 event cap - narrow the date range or scope and retry.",
        );
      } else if (status === 403 || msg.includes("403")) {
        toast.error(
          "You do not have permission to export this project.",
        );
      } else if (status === 404 || msg.includes("404")) {
        toast.error("Project not found. It may have been deleted.");
      } else {
        toast.error(`Export failed. Try again or contact support. ${msg}`);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && !busy && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Export project</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Format</Label>
            <RadioGroup
              value={format}
              onValueChange={(v) => setFormat(v as Format)}
              className="gap-2"
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem value="stix" id="fmt-stix" />
                <Label htmlFor="fmt-stix" className="font-normal">
                  <span className="font-medium">STIX 2.1 Bundle</span>{" "}
                  <span className="brand-mono text-muted-foreground">
                    (.stix.json)
                  </span>{" "}
                  - events + project metadata + scope rows as a STIX bundle
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="csv" id="fmt-csv" />
                <Label htmlFor="fmt-csv" className="font-normal">
                  <span className="font-medium">CSV</span>{" "}
                  <span className="brand-mono text-muted-foreground">
                    (.csv)
                  </span>{" "}
                  - one row per event, flattened for spreadsheet analysis
                </Label>
              </div>
            </RadioGroup>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="export-from">From (optional)</Label>
              <input
                id="export-from"
                type="date"
                value={fromDate}
                onChange={(e) => setFromDate(e.target.value)}
                className="w-full h-9 rounded-md border border-input bg-transparent px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-signal)]"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="export-to">To (optional)</Label>
              <input
                id="export-to"
                type="date"
                value={toDate}
                onChange={(e) => setToDate(e.target.value)}
                className="w-full h-9 rounded-md border border-input bg-transparent px-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-signal)]"
              />
            </div>
          </div>

          <p className="text-xs text-muted-foreground">
            Date-range filtering is advisory in - the export endpoint
            currently returns all in-scope events up to the 50,000-event cap.
            If the cap is reached, narrow the project scope and retry. Async
            large-export jobs are a v2.1 candidate.
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            onClick={submit}
            disabled={busy}
            style={{
              backgroundColor: "var(--brand-signal)",
              color: "var(--brand-ink)",
            }}
          >
            {busy ? "Exporting…" : "Export"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
