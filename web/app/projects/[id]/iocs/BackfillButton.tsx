"use client";

/**
 * BackfillButton — (UI-SPEC §Surface 6).
 *
 * Admin-only widget that triggers POST /api/admin/iocs/backfill (returns
 * 202 + {job_id}) and polls GET /api/jobs/{job_id} every 1.5s until the
 * actor reports complete or failed. Async pattern from Plan 22-04.
 */

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";

import {
  triggerBackfill,
  pollJobStatus,
  type IOCJobStatus,
} from "@/app/api-client";
import { useProjectRole } from "@/app/projects/[id]/ProjectRoleProvider";

const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS = 5 * 60 * 1000;

interface Props {
  projectId: string;
  onComplete: () => void;
}

export function BackfillButton({ projectId, onComplete }: Props) {
  const { isAdmin } = useProjectRole();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [starting, setStarting] = useState(false);
  const pollTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (pollTimerRef.current !== null) {
        window.clearTimeout(pollTimerRef.current);
      }
    };
  }, []);

  if (!isAdmin) return null;

  async function startPoll(jobId: string) {
    const startTs = Date.now();
    const tick = async () => {
      try {
        const status: IOCJobStatus = await pollJobStatus(jobId);
        if (status.status === "complete") {
          setRunning(false);
          toast.success(
            `Backfill complete: ${status.iocs_inserted ?? 0} new IOCs (events processed: ${status.events_processed ?? 0}).`,
          );
          onComplete();
          return;
        }
        if (status.status === "failed") {
          setRunning(false);
          toast.error(`Backfill failed. ${status.error ?? ""}`);
          return;
        }
        if (Date.now() - startTs > POLL_TIMEOUT_MS) {
          setRunning(false);
          toast.warning(
            "Backfill is taking longer than expected. Continuing in the background.",
          );
          return;
        }
        pollTimerRef.current = window.setTimeout(
          () => void tick(),
          POLL_INTERVAL_MS,
        );
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        setRunning(false);
        toast.error(`Backfill polling failed. ${msg}`);
      }
    };
    pollTimerRef.current = window.setTimeout(() => void tick(), POLL_INTERVAL_MS);
  }

  async function run() {
    setStarting(true);
    try {
      const { job_id } = await triggerBackfill(projectId);
      setConfirmOpen(false);
      setRunning(true);
      void startPoll(job_id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Backfill failed to start. ${msg}`);
    } finally {
      setStarting(false);
    }
  }

  return (
    <>
      <Button
        size="sm"
        variant="outline"
        onClick={() => setConfirmOpen(true)}
        disabled={running}
      >
        <RefreshCw className="h-4 w-4 mr-2" />
        Backfill
      </Button>

      {running && (
        <div className="absolute left-0 right-0 top-0 -mt-2 px-6">
          <Alert>
            <Loader2 className="h-4 w-4 animate-spin" />
            <AlertTitle>Backfill in progress</AlertTitle>
            <AlertDescription>
              Indicators are being extracted in the background. This may take a
              few minutes for large projects.
            </AlertDescription>
          </Alert>
        </div>
      )}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Run IOC backfill?</DialogTitle>
            <DialogDescription>
              This re-extracts atomic indicators from every existing event in
              this project (and any global events) and inserts new IOC rows.
              Existing rows are preserved via deduplication; the operation is
              safe to repeat.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setConfirmOpen(false)}
              disabled={starting}
            >
              Cancel
            </Button>
            <Button onClick={() => void run()} disabled={starting}>
              {starting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Starting…
                </>
              ) : (
                "Run backfill"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
