"use client";

/**
 * ScanDetailClient - (UI-SPEC §Surface 6).
 *
 * Renders:
 *   - Breadcrumb: EASM / Scan History / <scan_id short>
 *   - Scan metadata card (grid grid-cols-2 gap-4)
 *   - shadcn Tabs: "Findings" | "Diff vs previous"
 *     - Findings tab reuses FindingsTable filtered to scan_id
 *     - Diff tab lazy-loads DiffView on first select
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FindingsTable } from "../../FindingsTable";
import { DiffView } from "./DiffView";
import type { EASMFinding, EASMScan, ScanStatus } from "../../lib/api";
import { listFindings, listScans } from "../../lib/api";

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

function fmtDatetime(iso: string | null): string {
  if (!iso) return "-";
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

// ---------------------------------------------------------------------------
// ScanDetailClient
// ---------------------------------------------------------------------------

interface ScanDetailClientProps {
  projectId: string;
  scanId: string;
  /** True when the current user has Observer role (cannot patch findings) */
  isObserver?: boolean;
}

export function ScanDetailClient({
  projectId,
  scanId,
  isObserver = false,
}: ScanDetailClientProps) {
  const router = useRouter();
  const [scan, setScan] = useState<EASMScan | null>(null);
  const [findings, setFindings] = useState<EASMFinding[]>([]);
  const [loadingScan, setLoadingScan] = useState(true);
  const [loadingFindings, setLoadingFindings] = useState(true);
  const [scanError, setScanError] = useState<string | null>(null);
  const [findingsError, setFindingsError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"findings" | "diff">("findings");
  const [diffActivated, setDiffActivated] = useState(false);

  // -----------------------------------------------------------------------
  // Fetch scan metadata
  // -----------------------------------------------------------------------
  useEffect(() => {
    setLoadingScan(true);
    setScanError(null);
    listScans(projectId)
      .then((scans) => {
        const found = scans.find((s) => s.id === scanId) ?? null;
        setScan(found);
        if (!found) setScanError("Scan not found.");
      })
      .catch((err) => {
        const msg = err instanceof Error ? err.message : "error";
        setScanError(`Could not load scan details. ${msg}`);
      })
      .finally(() => setLoadingScan(false));
  }, [projectId, scanId]);

  // -----------------------------------------------------------------------
  // Fetch findings for this scan
  // -----------------------------------------------------------------------
  useEffect(() => {
    setLoadingFindings(true);
    setFindingsError(null);
    listFindings(projectId, { limit: 200 })
      .then((all) => {
        // Filter client-side to scan_id (API supports scan_id filter in later plans)
        setFindings(all.filter((f) => f.scan_id === scanId));
      })
      .catch((err) => {
        const msg = err instanceof Error ? err.message : "error";
        setFindingsError(`Could not load findings. ${msg}`);
      })
      .finally(() => setLoadingFindings(false));
  }, [projectId, scanId]);

  // -----------------------------------------------------------------------
  // Tab change handler - lazy-load diff
  // -----------------------------------------------------------------------
  function handleTabChange(value: string) {
    setActiveTab(value as "findings" | "diff");
    if (value === "diff" && !diffActivated) {
      setDiffActivated(true);
    }
  }

  // -----------------------------------------------------------------------
  // Finding update handler
  // -----------------------------------------------------------------------
  function handleFindingUpdate(updated: EASMFinding) {
    setFindings((prev) => prev.map((f) => (f.id === updated.id ? updated : f)));
  }

  // -----------------------------------------------------------------------
  // Short scan ID for breadcrumb
  // -----------------------------------------------------------------------
  const shortId = scanId.slice(0, 8);

  // -----------------------------------------------------------------------
  // Render: loading / error states
  // -----------------------------------------------------------------------
  if (loadingScan) {
    return (
      <div className="space-y-4">
        <div className="h-5 w-64 rounded bg-card/60 animate-pulse" />
        <div className="h-32 rounded-md border border-border bg-card/50 animate-pulse" />
      </div>
    );
  }

  if (scanError || !scan) {
    return (
      <div className="space-y-4">
        <p className="text-destructive text-sm">{scanError ?? "Scan not found."}</p>
      </div>
    );
  }

  const statusVariant = STATUS_VARIANT[scan.status] ?? "outline";

  return (
    <div className="space-y-4">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1 text-sm text-muted-foreground">
        <button
          type="button"
          className="hover:text-foreground transition-colors"
          onClick={() => router.push(`/projects/${projectId}/easm`)}
        >
          EASM
        </button>
        <span>/</span>
        <button
          type="button"
          className="hover:text-foreground transition-colors"
          onClick={() => router.push(`/projects/${projectId}/easm/scans`)}
        >
          Scan History
        </button>
        <span>/</span>
        <span className="font-mono text-foreground">{shortId}</span>
      </nav>

      {/* Scan metadata card */}
      <div className="bg-card border border-border rounded-md p-4 grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <p className="brand-caption text-muted-foreground">Mode</p>
          <span
            className={`brand-caption font-medium px-2 py-0.5 rounded-full ${
              scan.scan_mode === "active"
                ? "bg-[var(--brand-signal)] text-[var(--brand-ink,#04342c)]"
                : "text-muted-foreground border border-border"
            }`}
          >
            {scan.scan_mode === "active" ? "Active" : "Passive"}
          </span>
        </div>

        <div className="space-y-1">
          <p className="brand-caption text-muted-foreground">Status</p>
          <Badge variant={statusVariant} className="brand-caption capitalize">
            {scan.status}
          </Badge>
        </div>

        <div className="space-y-1">
          <p className="brand-caption text-muted-foreground">Started</p>
          <p className="text-sm text-foreground">{fmtDatetime(scan.started_at)}</p>
        </div>

        <div className="space-y-1">
          <p className="brand-caption text-muted-foreground">Finished</p>
          <p className="text-sm text-foreground">{fmtDatetime(scan.finished_at)}</p>
        </div>

        <div className="space-y-1">
          <p className="brand-caption text-muted-foreground">Launched by</p>
          <p className="font-mono text-[12px] text-foreground break-all">
            {scan.launched_by}
          </p>
        </div>

        <div className="space-y-1">
          <p className="brand-caption text-muted-foreground">Findings</p>
          <p className="text-sm text-foreground">{scan.findings_count}</p>
        </div>

        {scan.error && (
          <div className="col-span-2 space-y-1">
            <p className="brand-caption text-muted-foreground">Error</p>
            <p className="text-sm text-destructive">{scan.error}</p>
          </div>
        )}
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={handleTabChange}>
        <TabsList>
          <TabsTrigger value="findings">Findings</TabsTrigger>
          <TabsTrigger value="diff">Diff vs previous</TabsTrigger>
        </TabsList>

        {/* Findings tab */}
        <TabsContent value="findings" className="mt-4">
          {loadingFindings ? (
            <div className="rounded-md border border-border overflow-hidden">
              {Array.from({ length: 5 }).map((_, i) => (
                <div
                  key={i}
                  className="h-[44px] border-b border-border/40 last:border-b-0 bg-card/50 animate-pulse"
                />
              ))}
            </div>
          ) : findingsError ? (
            <p className="text-destructive text-sm">{findingsError}</p>
          ) : findings.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
              <h2 className="text-[22px] font-medium leading-[1.3]">
                No findings in this scan
              </h2>
              <p className="text-muted-foreground max-w-md leading-[1.7]">
                BBOT completed without discovering any findings in scope. Try
                adjusting the scope or adding more modules.
              </p>
            </div>
          ) : (
            <FindingsTable
              findings={findings}
              isObserver={isObserver}
              onFindingUpdate={handleFindingUpdate}
            />
          )}
        </TabsContent>

        {/* Diff tab - lazy-loaded on first select */}
        <TabsContent value="diff" className="mt-4">
          {diffActivated ? (
            <DiffView projectId={projectId} scanId={scanId} />
          ) : null}
        </TabsContent>
      </Tabs>
    </div>
  );
}
