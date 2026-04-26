"use client";

/**
 * AIRerankCard — AI Re-ranking card for /projects/[id]/scoring (Phase 17 plan 17-09 / SCR-04).
 * Surface 5 per 17-UI-SPEC.md.
 *
 * Only rendered when aiRerankEnabled === true.
 * Mirrors Phase 15 Card 4 Rescore Status polling pattern exactly:
 *   - POST /api/projects/{id}/ai/rerank → queue toast → start 3s polling
 *   - GET  /api/projects/{id}/ai/rerank/status → in_progress_count > 0 → show progress
 *   - Transition to 0: clearInterval → complete toast → update last_rerank_at
 *   - HTTP error: clearInterval → error toast
 *   - Cleanup: useEffect return clears interval
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// ---------------------------------------------------------------------------
// Types matching backend schemas/ai.py AIRerankStatus
// ---------------------------------------------------------------------------

interface AIRerankStatus {
  last_rerank_at: string | null;
  in_progress_count: number;
  total_count: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function relativeTime(iso: string | null): string {
  if (!iso) return "Not yet re-ranked";
  const diffMs = Date.now() - Date.parse(iso);
  if (diffMs < 0) return "just now";
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.floor(diffHr / 24)}d ago`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  projectId: string;
  aiRerankEnabled: boolean;
  onComplete?: () => void;
}

export function AIRerankCard({ projectId, aiRerankEnabled, onComplete }: Props) {
  const [rerankStatus, setRerankStatus] = useState<AIRerankStatus | null>(null);
  const [polling, setPolling] = useState(false);
  const wasPollingActive = useRef(false);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchRerankStatus = useCallback(async (): Promise<AIRerankStatus | null> => {
    try {
      const res = await fetch(`/api/projects/${projectId}/ai/rerank/status`, {
        credentials: "include",
      });
      if (!res.ok) return null;
      return (await res.json()) as AIRerankStatus;
    } catch {
      return null;
    }
  }, [projectId]);

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    setPolling(false);
    wasPollingActive.current = false;
  }, []);

  const startPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    setPolling(true);
    pollIntervalRef.current = setInterval(async () => {
      const status = await fetchRerankStatus();
      if (!status) {
        stopPolling();
        toast.error("Re-ranking status check failed.");
        return;
      }
      setRerankStatus(status);
      if (status.in_progress_count > 0) {
        wasPollingActive.current = true;
      } else if (wasPollingActive.current) {
        // Was > 0, now 0 → re-rank complete
        stopPolling();
        toast.success(`AI re-ranking complete — ${status.total_count} events updated.`);
        onComplete?.();
      }
    }, 3000);
  }, [fetchRerankStatus, stopPolling, onComplete]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  // Load initial status on mount
  useEffect(() => {
    if (!aiRerankEnabled) return;
    fetchRerankStatus().then((status) => {
      if (status) setRerankStatus(status);
    });
  }, [aiRerankEnabled, fetchRerankStatus]);

  async function handleRerank() {
    try {
      const res = await fetch(`/api/projects/${projectId}/ai-rescore`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        const msg = await res.text().catch(() => "Unknown error.");
        toast.error(`Could not trigger re-ranking. ${msg}`);
        return;
      }
      toast.success("AI re-ranking queued.");
      startPolling();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error.";
      toast.error(`Could not trigger re-ranking. ${msg}`);
    }
  }

  // Gate: only render when AI rerank is enabled
  if (!aiRerankEnabled) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="brand-heading">AI Re-ranking</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-4">
            <span className="text-sm text-muted-foreground">
              Last re-ranked {relativeTime(rerankStatus?.last_rerank_at ?? null)}
            </span>
            {polling && rerankStatus && rerankStatus.in_progress_count > 0 && (
              <span className="text-sm text-foreground flex items-center gap-1">
                <span className="animate-pulse">●</span>
                Re-ranking… {rerankStatus.total_count - rerankStatus.in_progress_count} /{" "}
                {rerankStatus.total_count}
              </span>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRerank}
            disabled={polling}
          >
            Re-rerank now
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
