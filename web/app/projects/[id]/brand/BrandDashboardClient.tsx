"use client";

/**
 * BrandDashboardClient — (UI-SPEC §Surface 2 + §Surface 3).
 *
 * Owns:
 *   - Filter state (severity / source / lifecycle / include_dismissed)
 *   - Dashboard fetch (on mount + filter change via cancel-flag pattern)
 *   - Suppression-review banner (conditional on has_expiring_dismissals)
 *   - Noise-downgrade banner (conditional on has_recent_auto_downgrade)
 *   - Empty state + error state + loading skeleton
 *   - "Manage brand terms →" right-aligned link
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import type {
  BrandDashboardResponse,
  BrandMatchFilters,
  BrandMatchRead,
  MatchDetailsResponse,
} from "./lib/api";
import { listBrandMatches, fetchBrandMatchDetails } from "./lib/api";
import { MatchFilterBar } from "./MatchFilterBar";
import { MatchTable } from "./MatchTable";
import { SuppressionReviewBanner } from "./SuppressionReviewBanner";
import { MatchDetailDrawer } from "./MatchDetailDrawer";

// ---------------------------------------------------------------------------
// Brand sub-tab strip (Matches | Terms | Stoplist)
// Tab order: Matches (default) | Terms | Stoplist — UI-SPEC §Surface 1
// ---------------------------------------------------------------------------

interface BrandTab {
  key: string;
  label: string;
  route: (projectId: string) => string;
  active: (pathname: string) => boolean;
}

const BRAND_TABS: BrandTab[] = [
  {
    key: "matches",
    label: "Matches",
    route: (id) => `/projects/${id}/brand`,
    active: (p) =>
      p.endsWith("/brand") || (p.includes("/brand") && !p.includes("/brand/terms") && !p.includes("/brand/stoplist")),
  },
  {
    key: "terms",
    label: "Terms",
    route: (id) => `/projects/${id}/brand/terms`,
    active: (p) => p.includes("/brand/terms"),
  },
  {
    key: "stoplist",
    label: "Stoplist",
    route: (id) => `/projects/${id}/brand/stoplist`,
    active: (p) => p.includes("/brand/stoplist"),
  },
];

function BrandTabStrip({ projectId }: { projectId: string }) {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <div className="flex items-center gap-1 border-b border-border pb-0 mb-4">
      {BRAND_TABS.map((tab) => {
        const isActive = tab.active(pathname ?? "");
        return (
          <button
            key={tab.key}
            type="button"
            onClick={() => router.push(tab.route(projectId))}
            className={[
              "px-4 py-2 text-sm font-medium border-b-2 transition-colors",
              isActive
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground",
            ].join(" ")}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton rows (loading state — mirrors FindingsSkeleton)
// ---------------------------------------------------------------------------
function MatchesSkeleton() {
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
// BrandDashboardClient
// ---------------------------------------------------------------------------
interface BrandDashboardClientProps {
  projectId: string;
  /** Test-only — override observer-role detection. */
  isObserver?: boolean;
}

export function BrandDashboardClient({
  projectId,
  isObserver = false,
}: BrandDashboardClientProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Drawer URL state — ?match=<uuid>
  const activeMatchId = searchParams.get("match");
  const [drawerDetails, setDrawerDetails] = useState<MatchDetailsResponse | null>(null);
  const [drawerMatch, setDrawerMatch] = useState<BrandMatchRead | null>(null);

  const [data, setData] = useState<BrandDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<BrandMatchFilters>({});

  const fetchMatches = useCallback(
    async (currentFilters: BrandMatchFilters, signal: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const resp = await listBrandMatches(projectId, currentFilters);
        if (!signal.aborted) setData(resp);
      } catch (err) {
        if (!signal.aborted) {
          const msg = err instanceof Error ? err.message : "error";
          setError(`Could not load matches. ${msg}`);
        }
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    },
    [projectId],
  );

  useEffect(() => {
    const controller = new AbortController();
    fetchMatches(filters, controller.signal);
    return () => controller.abort();
  }, [fetchMatches, filters]);

  // Open drawer when ?match= URL param is present
  useEffect(() => {
    if (!activeMatchId) {
      setDrawerDetails(null);
      setDrawerMatch(null);
      return;
    }
    // Find the match object in local state
    const found = data?.matches.find((m) => m.id === activeMatchId) ?? null;
    setDrawerMatch(found);
    // Fetch details for the drawer
    fetchBrandMatchDetails(projectId, activeMatchId)
      .then(setDrawerDetails)
      .catch((err: unknown) => {
        const status = (err as { status?: number }).status;
        if (status === 404) {
          toast.error("Match not found.");
          router.push(pathname, { scroll: false });
        } else {
          // Details failed but drawer can still open with match data
          setDrawerDetails(null);
        }
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMatchId, projectId]);

  // Sync drawerMatch when matches data refreshes
  useEffect(() => {
    if (!activeMatchId || !data) return;
    const found = data.matches.find((m) => m.id === activeMatchId) ?? null;
    if (found) setDrawerMatch(found);
  }, [data, activeMatchId]);

  // Called when matched_value cell is clicked — push URL param (shallow)
  function handleMatchClick(matchId: string) {
    router.push(`${pathname}?match=${matchId}`, { scroll: false });
  }

  // Close drawer — clear URL param
  function handleDrawerClose() {
    router.push(pathname, { scroll: false });
  }

  // Optimistic update after in-row lifecycle PATCH
  function handleMatchUpdate(updated: BrandMatchRead) {
    setData((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        matches: prev.matches.map((m) =>
          m.id === updated.id ? { ...m, ...updated } : m,
        ),
      };
    });
  }

  const matches = data?.matches ?? [];

  // ---- Noise-downgrade banner copy --------------------------------------
  const downgradeTerms = data?.recent_auto_downgrade_terms ?? [];
  const downgradeCounts = data?.recent_auto_downgrade_counts ?? {};
  function renderNoiseDowngradeBanner() {
    if (!data?.has_recent_auto_downgrade) return null;
    const n = downgradeTerms.length;
    if (n === 0) return null;
    if (n > 3) {
      return (
        <div
          className="border-l-4 border-[var(--brand-signal)] bg-accent/10 px-4 py-3 rounded-sm"
          role="alert"
        >
          <p className="text-sm text-foreground">
            {n} terms auto-downgraded to watch-only due to noise threshold.
            Review on the Terms tab.
          </p>
        </div>
      );
    }
    // Single or small-N: one banner per term
    return (
      <div className="space-y-2">
        {downgradeTerms.map((value) => {
          const count = downgradeCounts[value] ?? 0;
          return (
            <div
              key={value}
              className="border-l-4 border-[var(--brand-signal)] bg-accent/10 px-4 py-3 rounded-sm"
              role="alert"
            >
              <p className="text-sm text-foreground">
                Term &apos;{value}&apos; auto-downgraded to watch-only — {count}{" "}
                matches in last 24h. Review on the Terms tab.
              </p>
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Brand sub-tab strip: Matches | Terms | Stoplist */}
      <BrandTabStrip projectId={projectId} />

      {/* Suppression-review banner (clickable — opens modal) */}
      {data?.has_expiring_dismissals && (
        <SuppressionReviewBanner
          projectId={projectId}
          count={data.expiring_dismissals_count ?? 0}
          canEdit={!isObserver}
        />
      )}

      {/* Noise-downgrade banner(s) */}
      {renderNoiseDowngradeBanner()}

      {/* Filter bar */}
      <div className="flex items-center gap-4 flex-wrap">
        <MatchFilterBar filters={filters} onChange={setFilters} />
      </div>

      {/* Content: loading / error / empty / table */}
      {loading ? (
        <MatchesSkeleton />
      ) : error ? (
        <div className="flex items-center gap-3 py-6 text-destructive text-sm">
          <span>{error}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              const controller = new AbortController();
              fetchMatches(filters, controller.signal);
            }}
          >
            Retry
          </Button>
        </div>
      ) : matches.length === 0 ? (
        /* Empty state — UI-SPEC canonical copy */
        <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
          <h2 className="text-[22px] font-medium leading-[1.3]">
            No brand matches yet.
          </h2>
          <p className="text-muted-foreground max-w-md leading-[1.7]">
            Add brand terms to start monitoring.
          </p>
          <Button
            variant="default"
            onClick={() => router.push(`/projects/${projectId}/brand/terms`)}
          >
            Add brand term
          </Button>
        </div>
      ) : (
        <MatchTable
          matches={matches}
          isObserver={isObserver}
          onMatchUpdate={handleMatchUpdate}
          onMatchClick={handleMatchClick}
          activeMatchId={activeMatchId}
        />
      )}

      {/* Match detail drawer — mounts when ?match= param is set and details loaded */}
      {activeMatchId && drawerMatch && drawerDetails && (
        <MatchDetailDrawer
          projectId={projectId}
          match={drawerMatch}
          details={drawerDetails}
          open={true}
          onClose={handleDrawerClose}
          onUpdate={(updated) => {
            handleMatchUpdate(updated);
            // Refetch details to refresh history/counts in drawer
            fetchBrandMatchDetails(projectId, updated.id)
              .then(setDrawerDetails)
              .catch(() => {/* non-fatal */});
          }}
        />
      )}
    </div>
  );
}
