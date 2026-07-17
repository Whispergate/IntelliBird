"use client";

/**
 * PublishModal — Surface 9. Confirmation dialog before locking/publishing a report.
 * UI-SPEC §Surface 9.
 *
 * Buttons:
 *   - "Lock and publish" (destructive) — calls publishReport, toasts success
 *   - "Keep editing" — closes without changes
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { publishReport } from "../lib/api";

interface PublishModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  reportId: string;
  reportTitle: string;
}

export function PublishModal({
  open,
  onOpenChange,
  projectId,
  reportId,
  reportTitle,
}: PublishModalProps) {
  const router = useRouter();
  const [publishing, setPublishing] = useState(false);

  async function onPublish() {
    setPublishing(true);
    try {
      await publishReport({ projectId, reportId });
      toast.success("Report published.");
      onOpenChange(false);
      router.refresh();
    } catch (e) {
      toast.error(
        `Could not publish report. ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setPublishing(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Publish this report?</DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground mt-1">
            Publishing &ldquo;{reportTitle}&rdquo; will lock all sections and scenarios. This
            action cannot be undone without cloning to a new draft.
          </DialogDescription>
        </DialogHeader>

        <div className="py-2 space-y-1.5">
          <p className="text-sm font-medium">What gets locked:</p>
          <ul className="text-sm text-muted-foreground space-y-0.5 list-disc list-inside">
            <li>All 6 report sections (Scope, AIA, Threat Landscape, Actor Profiles, Scenarios, Scenario X)</li>
            <li>Threat scenario chains and procedure text</li>
            <li>CBEST mode setting</li>
          </ul>
          <p className="text-xs text-muted-foreground mt-2">
            To continue editing after publishing, use &ldquo;Clone to new draft&rdquo; — the
            published version remains intact.
          </p>
        </div>

        <DialogFooter className="gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={publishing}>
            Keep editing
          </Button>
          <Button
            variant="destructive"
            onClick={onPublish}
            disabled={publishing}
          >
            {publishing ? "Publishing…" : "Lock and publish"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
