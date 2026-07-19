"use client";

/**
 * EASMDashboardClient - (UI-SPEC §Surface 3).
 *
 * Owns:
 *   - Filter state (type, module, severity, lifecycle, include_dismissed)
 *   - Findings list (fetched on mount + filter change via useEffect cancel-flag pattern)
 *   - Safelist data (for module filter options)
 *   - Project data (for 24h-banner active_auth_confirmed_at gating)
 *   - Scan controls bar + concurrent-scan count badge
 *   - 24h-warning amber banner (conditional)
 *   - Empty state + error state + loading skeleton
 *
 * Scan launch dialog: placeholder toast until plan 11-09 replaces the import.
 *
 * 24h banner logic:
 *   Renders when project.active_scans_authorised === true
 *   AND NOW() - active_auth_confirmed_at > 6 days.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";

import { Button } from "@/components/ui/button";
import { listMemberships } from "@/app/projects/lib/api";
import type {
  EASMFinding,
  EASMSafelist,
  FindingsFilters,
} from "./lib/api";
import { getSafelist, listFindings, listScans } from "./lib/api";
import { FindingsFilterBar } from "./FindingsFilterBar";
import { FindingsTable } from "./FindingsTable";
import { ScanLaunchDialog } from "./ScanLaunchDialog";

// Six days in milliseconds
const SIX_DAYS_MS = 6 * 24 * 60 * 60 * 1000;

interface ProjectBannerData {
  active_scans_authorised: boolean;
  active_auth_confirmed_at: string | null;
}

// ---------------------------------------------------------------------------
// Skeleton rows (loading state)
// ---------------------------------------------------------------------------
function FindingsSkeleton() {
  return (
    <div className="rounded-md border border-border overflow-hidden">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="h-[44px] border-b border-border/40 last:border-b-0 bg-card/50 animate-pulse"
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// EASMDashboardClient
// ---------------------------------------------------------------------------
interface EASMDashboardClientProps {
  projectId: string;
  /** Optional - passed by tests or by page if project is already available. */
  initialProject?: ProjectBannerData | null;
  /** Optional - passed by tests to control observer role display. */
  isObserver?: boolean;
  /** True when the current user has Lead or global Admin authority to launch active scans. */
  userIsLeadOrAdmin?: boolean;
}

export function EASMDashboardClient({
  projectId,
  initialProject = null,
  isObserver = false,
  userIsLeadOrAdmin = false,
}: EASMDashboardClientProps) {
  const router = useRouter();

  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------
  const [findings, setFindings] = useState<EASMFinding[]>([]);
  const [safelist, setSafelist] = useState<EASMSafelist | null>(null);
  const [project, setProject] = useState<ProjectBannerData | null>(
    initialProject,
  );
  const [runningCount, setRunningCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<FindingsFilters>({});
  const [launchDialogOpen, setLaunchDialogOpen] = useState(false);

  // Authority: dev-mode (no session) → Admin stub (mirrors backend AuthMiddleware).
  // Prop override (userIsLeadOrAdmin from page.tsx OR tests) wins.
  const { data: session } = useSession();
  const [computedAuthority, setComputedAuthority] = useState<boolean>(
    userIsLeadOrAdmin,
  );
  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const user = (session?.user as any) ?? null;
    if (!user) {
      setComputedAuthority(true);
      return;
    }
    if (user.role === "Admin") {
      setComputedAuthority(true);
      return;
    }
    listMemberships(projectId)
      .then((memberships) => {
        const isLead = memberships.some(
          (m) => m.user_sub === user.sub && m.project_role === "Lead",
        );
        setComputedAuthority(isLead);
      })
      .catch(() => setComputedAuthority(false));
  }, [session, projectId]);
  const effectiveAuthority = userIsLeadOrAdmin || computedAuthority;

  // -----------------------------------------------------------------------
  // 24h banner: rendered when gate is active AND confirmed_at > 6d ago
  // -----------------------------------------------------------------------
  const showBanner = (() => {
    if (!project?.active_scans_authorised) return false;
    if (!project.active_auth_confirmed_at) return false;
    const confirmedAt = new Date(project.active_auth_confirmed_at).getTime();
    const ageMs = Date.now() - confirmedAt;
    return ageMs > SIX_DAYS_MS;
  })();

  // -----------------------------------------------------------------------
  // Fetch findings + safelist on mount and on filter change
  // -----------------------------------------------------------------------
  const fetchFindings = useCallback(
    async (currentFilters: FindingsFilters, signal: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const [found, safe] = await Promise.all([
          listFindings(projectId, currentFilters),
          getSafelist(),
        ]);
        if (!signal.aborted) {
          setFindings(found);
          setSafelist(safe);
        }
      } catch (err) {
        if (!signal.aborted) {
          const msg = err instanceof Error ? err.message : "error";
          setError(`Could not load findings. ${msg}`);
        }
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    },
    [projectId],
  );

  useEffect(() => {
    const controller = new AbortController();
    fetchFindings(filters, controller.signal);
    return () => controller.abort();
  }, [fetchFindings, filters]);

  // -----------------------------------------------------------------------
  // Fetch project data for banner gating (if not provided)
  // -----------------------------------------------------------------------
  useEffect(() => {
    if (initialProject !== null) return; // provided externally - skip fetch
    let cancelled = false;
    fetch(`/api/projects/${projectId}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data) => {
        if (!cancelled) setProject(data as ProjectBannerData);
      })
      .catch(() => {
        // Banner gating is best-effort; don't show error for this
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, initialProject]);

  // -----------------------------------------------------------------------
  // Fetch running/queued scan count for badge
  // -----------------------------------------------------------------------
  const runningCountRef = useRef(runningCount);
  runningCountRef.current = runningCount;

  useEffect(() => {
    let cancelled = false;
    listScans(projectId)
      .then((scans) => {
        if (!cancelled) {
          const active = scans.filter(
            (s) => s.status === "running" || s.status === "queued",
          ).length;
          setRunningCount(active);
        }
      })
      .catch(() => {
        // Badge is best-effort
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // -----------------------------------------------------------------------
  // Optimistic update when lifecycle is patched in-row
  // -----------------------------------------------------------------------
  function handleFindingUpdate(updated: EASMFinding) {
    setFindings((prev) =>
      prev.map((f) => (f.id === updated.id ? updated : f)),
    );
  }

  // -----------------------------------------------------------------------
  // Refetch scans + findings after successful launch
  // -----------------------------------------------------------------------
  function handleLaunched() {
    const controller = new AbortController();
    fetchFindings(filters, controller.signal);
    // Also refresh running count
    listScans(projectId)
      .then((scans) => {
        const active = scans.filter(
          (s) => s.status === "running" || s.status === "queued",
        ).length;
        setRunningCount(active);
      })
      .catch(() => {});
  }

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  return (
    <div className="space-y-4">
      {/* Scan launch dialog */}
      <ScanLaunchDialog
        isOpen={launchDialogOpen}
        onClose={() => setLaunchDialogOpen(false)}
        projectId={projectId}
        project={project}
        userCanLaunchActive={effectiveAuthority}
        onLaunched={handleLaunched}
      />

      {/* Scan controls bar */}
      <div className="flex items-center gap-3">
        <Button
          variant="default"
          onClick={() => setLaunchDialogOpen(true)}
          className="font-medium"
        >
          Launch EASM Scan
        </Button>
        {runningCount > 0 && (
          <span className="brand-caption text-muted-foreground">
            {runningCount} scan{runningCount !== 1 ? "s" : ""} running
          </span>
        )}
      </div>

      {/* 24h-warning amber banner */}
      {showBanner && (
        <div
          className="border-l-4 border-[var(--brand-signal)] bg-accent/10 px-4 py-3 rounded-sm"
          role="alert"
        >
          <p className="text-sm text-foreground">
            Active-scan authorisation expires in less than 24 hours - re-confirm
            on the Settings tab before launching more active scans.
          </p>
        </div>
      )}

      {/* Filter bar */}
      <FindingsFilterBar
        filters={filters}
        onChange={setFilters}
        availableModules={safelist?.modules ?? []}
      />

      {/* Content: loading / error / empty / table */}
      {loading ? (
        <FindingsSkeleton />
      ) : error ? (
        <div className="flex items-center gap-3 py-6 text-destructive text-sm">
          <span>{error}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              const controller = new AbortController();
              fetchFindings(filters, controller.signal);
            }}
          >
            Retry
          </Button>
        </div>
      ) : findings.length === 0 ? (
        /* Empty state */
        <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
          <h2 className="text-[22px] font-medium leading-[1.3]">
            No EASM findings yet
          </h2>
          <p className="text-muted-foreground max-w-md leading-[1.7]">
            Launch a passive scan to begin discovering your project&apos;s
            external attack surface. Findings appear here as BBOT reports them.
          </p>
          <Button
            variant="default"
            onClick={() => setLaunchDialogOpen(true)}
          >
            Launch EASM Scan
          </Button>
        </div>
      ) : (
        <FindingsTable
          findings={findings}
          isObserver={isObserver}
          onFindingUpdate={handleFindingUpdate}
        />
      )}

      {/* View scan history link */}
      {!loading && (
        <div className="flex justify-end">
          <button
            type="button"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
            onClick={() =>
              router.push(`/projects/${projectId}/easm/scans`)
            }
          >
            View scan history →
          </button>
        </div>
      )}
    </div>
  );
}
