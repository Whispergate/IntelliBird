"use client";

/**
 * BrandDashboardClient — Phase 12 plan 12-08 (UI-SPEC §Surface 2 + §Surface 3).
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
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import type {
  BrandDashboardResponse,
  BrandMatchFilters,
  BrandMatchRead,
} from "./lib/api";
import { listBrandMatches } from "./lib/api";
import { MatchFilterBar } from "./MatchFilterBar";
import { MatchTable } from "./MatchTable";
import { SuppressionReviewBanner } from "./SuppressionReviewBanner";

// ---------------------------------------------------------------------------
// Skeleton rows (loading state — mirrors Phase 11 FindingsSkeleton)
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

      {/* Filter bar + Manage-terms link */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <MatchFilterBar filters={filters} onChange={setFilters} />
        <button
          type="button"
          className="text-[12px] text-muted-foreground hover:text-foreground transition-colors"
          onClick={() => router.push(`/projects/${projectId}/brand/terms`)}
        >
          Manage brand terms →
        </button>
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
        />
      )}
    </div>
  );
}
