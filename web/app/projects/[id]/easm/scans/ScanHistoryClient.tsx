"use client";

/**
 * ScanHistoryClient — (UI-SPEC §Surface 5).
 *
 * Scan history table at /projects/[id]/easm/scans.
 * Columns: Mode (100px) | Status (120px) | Started (140px) | Finished (140px) |
 *           Launched by (160px truncated 20ch) | Findings (80px) | Actions
 *
 * Running rows: pulsing amber dot + "Cancel scan" button (Lead/Admin/owner-Contributor).
 * Cancel uses native window.confirm per UI-SPEC destructive pattern.
 * Row click → /projects/[id]/easm/scans/[scanId].
 *
 * Empty state: "No scans yet" + body + "Go to EASM Dashboard" CTA.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { EASMScan, ScanMode, ScanStatus } from "../lib/api";
import { cancelScan, listScans } from "../lib/api";

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

function fmtDatetime(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const day = d.toLocaleDateString("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
    const time = d.toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
    });
    return `${day} ${time} UTC`;
  } catch {
    return iso.slice(0, 16);
  }
}

function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return `${str.slice(0, maxLen)}…`;
}

// ---------------------------------------------------------------------------
// Mode badge
// ---------------------------------------------------------------------------
function ModeBadge({ mode }: { mode: ScanMode }) {
  if (mode === "active") {
    return (
      <span
        className="brand-caption font-medium px-2 py-0.5 rounded-full"
        style={{ backgroundColor: "var(--brand-signal)", color: "var(--brand-ink, #04342c)" }}
      >
        Active
      </span>
    );
  }
  return (
    <span className="brand-caption font-medium text-muted-foreground px-2 py-0.5 rounded-full border border-border">
      Passive
    </span>
  );
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------
const STATUS_VARIANT: Record<
  ScanStatus,
  "outline" | "secondary" | "default" | "destructive"
> = {
  queued: "outline",
  running: "secondary",
  finished: "default",
  failed: "destructive",
  cancelled: "outline",
  orphaned: "outline",
};

function StatusBadge({ status, isRunning }: { status: ScanStatus; isRunning: boolean }) {
  const variant = STATUS_VARIANT[status] ?? "outline";
  return (
    <div className="flex items-center gap-1.5">
      {isRunning && (
        <span
          className="w-2 h-2 rounded-full bg-[var(--brand-signal)] animate-pulse shrink-0"
          aria-label="Scan is running"
        />
      )}
      <Badge variant={variant} className="brand-caption capitalize">
        {status}
      </Badge>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ScanHistoryClient
// ---------------------------------------------------------------------------

interface ScanHistoryClientProps {
  projectId: string;
  /** True when the current user has Lead/Admin authority (can cancel any scan) */
  userIsLeadOrAdmin?: boolean;
  /** Authentik sub of the current user (for Contributor own-scan cancel) */
  currentUserSub?: string;
}

export function ScanHistoryClient({
  projectId,
  userIsLeadOrAdmin = false,
  currentUserSub,
}: ScanHistoryClientProps) {
  const router = useRouter();
  const [scans, setScans] = useState<EASMScan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // -----------------------------------------------------------------------
  // Fetch scans on mount
  // -----------------------------------------------------------------------
  const fetchScans = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listScans(projectId);
      setScans(result);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "error";
      setError(`Could not load scan history. ${msg}`);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchScans();
  }, [fetchScans]);

  // -----------------------------------------------------------------------
  // Cancel handler
  // -----------------------------------------------------------------------
  async function handleCancel(scan: EASMScan, e: React.MouseEvent) {
    e.stopPropagation(); // don't navigate to detail
    const confirmed = window.confirm(
      "Cancel this scan? BBOT will stop and no further findings will be recorded.",
    );
    if (!confirmed) return;
    try {
      await cancelScan(projectId, scan.id);
      toast.success("Scan cancellation requested.");
      fetchScans();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "error";
      toast.error(`Could not cancel scan. ${msg}`);
    }
  }

  // -----------------------------------------------------------------------
  // Authority: can cancel this scan?
  // -----------------------------------------------------------------------
  function canCancel(scan: EASMScan): boolean {
    if (scan.status !== "running") return false;
    if (userIsLeadOrAdmin) return true;
    // Contributor can cancel their own scan
    if (currentUserSub && scan.launched_by === currentUserSub) return true;
    return false;
  }

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  if (loading) {
    return (
      <div className="space-y-4">
        <h1 className="text-[22px] font-medium leading-[1.3]">Scan History</h1>
        <div className="rounded-md border border-border overflow-hidden">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-[44px] border-b border-border/40 last:border-b-0 bg-card/50 animate-pulse"
            />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-[22px] font-medium leading-[1.3]">Scan History</h1>
        <p className="text-destructive text-sm">{error}</p>
        <Button variant="outline" size="sm" onClick={fetchScans}>
          Retry
        </Button>
      </div>
    );
  }

  if (scans.length === 0) {
    return (
      <div className="space-y-4">
        <h1 className="text-[22px] font-medium leading-[1.3]">Scan History</h1>
        <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
          <h2 className="text-[22px] font-medium leading-[1.3]">No scans yet</h2>
          <p className="text-muted-foreground max-w-md leading-[1.7]">
            Launch a scan from the EASM dashboard to start collecting findings.
          </p>
          <Button
            variant="default"
            onClick={() => router.push(`/projects/${projectId}/easm`)}
          >
            Go to EASM Dashboard
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h1 className="text-[22px] font-medium leading-[1.3]">Scan History</h1>
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-border bg-card text-left">
              <th
                className="py-2 px-3 brand-caption text-muted-foreground"
                style={{ width: "100px", minWidth: "100px" }}
              >
                Mode
              </th>
              <th
                className="py-2 px-3 brand-caption text-muted-foreground"
                style={{ width: "120px", minWidth: "120px" }}
              >
                Status
              </th>
              <th
                className="py-2 px-3 brand-caption text-muted-foreground"
                style={{ width: "140px", minWidth: "140px" }}
              >
                Started
              </th>
              <th
                className="py-2 px-3 brand-caption text-muted-foreground"
                style={{ width: "140px", minWidth: "140px" }}
              >
                Finished
              </th>
              <th
                className="py-2 px-3 brand-caption text-muted-foreground"
                style={{ width: "160px", minWidth: "160px" }}
              >
                Launched by
              </th>
              <th
                className="py-2 px-3 brand-caption text-muted-foreground"
                style={{ width: "80px", minWidth: "80px" }}
              >
                Findings
              </th>
              <th
                className="py-2 px-3 brand-caption text-muted-foreground"
                style={{ minWidth: "80px" }}
              >
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {scans.map((scan) => {
              const isRunning = scan.status === "running";
              const launchedByTruncated = truncate(scan.launched_by, 20);
              return (
                <tr
                  key={scan.id}
                  className="border-b border-border/40 last:border-b-0 cursor-pointer hover:bg-card/60 transition-colors"
                  style={{ height: "44px" }}
                  onClick={() =>
                    router.push(`/projects/${projectId}/easm/scans/${scan.id}`)
                  }
                >
                  {/* Mode */}
                  <td className="py-2 px-3" style={{ width: "100px" }}>
                    <ModeBadge mode={scan.scan_mode} />
                  </td>

                  {/* Status */}
                  <td className="py-2 px-3" style={{ width: "120px" }}>
                    <StatusBadge status={scan.status} isRunning={isRunning} />
                  </td>

                  {/* Started */}
                  <td
                    className="py-2 px-3 text-foreground text-sm"
                    style={{ width: "140px" }}
                  >
                    {fmtDatetime(scan.started_at)}
                  </td>

                  {/* Finished */}
                  <td
                    className="py-2 px-3 text-foreground text-sm"
                    style={{ width: "140px" }}
                  >
                    {fmtDatetime(scan.finished_at)}
                  </td>

                  {/* Launched by — truncated, tooltip for full value */}
                  <td className="py-2 px-3" style={{ width: "160px" }}>
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="font-mono text-[12px] text-foreground">
                            {launchedByTruncated}
                          </span>
                        </TooltipTrigger>
                        {scan.launched_by.length > 20 && (
                          <TooltipContent className="font-mono text-xs max-w-[400px] break-all">
                            {scan.launched_by}
                          </TooltipContent>
                        )}
                      </Tooltip>
                    </TooltipProvider>
                  </td>

                  {/* Findings count */}
                  <td
                    className="py-2 px-3 text-foreground text-sm"
                    style={{ width: "80px" }}
                  >
                    {scan.findings_count}
                  </td>

                  {/* Actions */}
                  <td className="py-2 px-3">
                    {canCancel(scan) && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={(e) => handleCancel(scan, e)}
                      >
                        Cancel scan
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
