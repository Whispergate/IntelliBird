"use client";

/**
 * AssetsClient — Phase 12.1 plans 12.1-05a (shell) + 12.1-05b (table+drawer wire-in).
 *
 * Client component owning:
 *   - Filter state parsed from useSearchParams (URL-as-single-source-of-truth)
 *   - Summary fetch on mount + filter change
 *   - List fetch (paginated, sorted) → AssetsTable
 *   - AssetDetailDrawer mounted when ?asset= URL param is set
 *   - Export dropdown (disabled when total === 0)
 *   - Empty-state rendering (two variants: filtered-zero vs project-no-findings)
 *
 * URL-sync pattern mirrors /events EventsClient: router.replace with shallow updates.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { AssetSummaryCards } from "./components/AssetSummaryCards";
import {
  AssetsFilterBar,
  type AssetFilters,
  type StaleFilterValue,
} from "./components/AssetsFilterBar";
import {
  AssetsTable,
  type AssetRow,
  type AssetSortKey,
  type AssetSortState,
} from "./components/AssetsTable";
import { AssetDetailDrawer } from "./components/AssetDetailDrawer";

// ---------------------------------------------------------------------------
// Local type surface — generated api-client types land in 12.1-06.
// Shapes mirror backend schemas (12.1-02) so later codegen is a drop-in swap.
// ---------------------------------------------------------------------------

export interface AssetSummaryBucket {
  count: number;
  stale_count: number;
}

export type AssetSummaryMap = Record<string, AssetSummaryBucket>;

interface AssetListResponse {
  items: AssetRow[];
  total: number;
  limit: number;
  offset: number;
}

interface AssetSummaryResponse {
  buckets: AssetSummaryMap;
}

/**
 * Bucket key → BBOT event types folded into that bucket.
 * UI-SPEC §Surface 3 (locked; consumed by summary card onClick).
 */
export const BUCKET_TYPE_MAP: Record<string, readonly string[]> = {
  DOMAINS: ["DNS_NAME", "URL_HOSTNAME"],
  IPS: ["IP_ADDRESS"],
  OPEN_PORTS: ["OPEN_TCP_PORT"],
  URLS: ["URL", "URL_UNVERIFIED"],
  TECHNOLOGIES: ["TECHNOLOGY", "WAF"],
  IDENTITIES: ["EMAIL_ADDRESS", "USERNAME"],
  OTHER: [],
};

/** Stable bucket iteration order — UI-SPEC locked. */
export const BUCKET_ORDER = [
  "DOMAINS",
  "IPS",
  "OPEN_PORTS",
  "URLS",
  "TECHNOLOGIES",
  "IDENTITIES",
  "OTHER",
] as const;

// ---------------------------------------------------------------------------
// URL ↔ filter helpers (mirror EventsClient pattern exactly).
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50;
const DEFAULT_SORT: AssetSortState = { key: "last_seen", direction: "desc" };
const SORT_KEYS: readonly AssetSortKey[] = [
  "type",
  "target",
  "first_seen",
  "last_seen",
  "scan_count",
];

function parseFiltersFromSearchParams(sp: URLSearchParams): AssetFilters {
  const staleRaw = sp.get("stale");
  const stale: StaleFilterValue =
    staleRaw === "hide" || staleRaw === "only" ? staleRaw : "show";
  return {
    type: sp.getAll("type"),
    scope: sp.getAll("scope"),
    stale,
    module: sp.getAll("module"),
    first_seen_from: sp.get("first_seen_from") ?? "",
    first_seen_to: sp.get("first_seen_to") ?? "",
    last_seen_from: sp.get("last_seen_from") ?? "",
    last_seen_to: sp.get("last_seen_to") ?? "",
    scan_id: sp.get("scan_id") ?? "",
    search: sp.get("search") ?? "",
  };
}

function buildSearchParams(filters: AssetFilters): URLSearchParams {
  const params = new URLSearchParams();
  for (const t of filters.type) params.append("type", t);
  for (const s of filters.scope) params.append("scope", s);
  if (filters.stale !== "show") params.set("stale", filters.stale);
  for (const m of filters.module) params.append("module", m);
  if (filters.first_seen_from) params.set("first_seen_from", filters.first_seen_from);
  if (filters.first_seen_to) params.set("first_seen_to", filters.first_seen_to);
  if (filters.last_seen_from) params.set("last_seen_from", filters.last_seen_from);
  if (filters.last_seen_to) params.set("last_seen_to", filters.last_seen_to);
  if (filters.scan_id) params.set("scan_id", filters.scan_id);
  if (filters.search) params.set("search", filters.search);
  return params;
}

function isAnyFilterActive(f: AssetFilters): boolean {
  return (
    f.type.length > 0 ||
    f.scope.length > 0 ||
    f.stale !== "show" ||
    f.module.length > 0 ||
    f.first_seen_from !== "" ||
    f.first_seen_to !== "" ||
    f.last_seen_from !== "" ||
    f.last_seen_to !== "" ||
    f.scan_id !== "" ||
    f.search !== ""
  );
}

function parseSortFromSearchParams(sp: URLSearchParams): AssetSortState {
  const raw = sp.get("sort");
  if (!raw) return DEFAULT_SORT;
  const [keyRaw, dirRaw] = raw.split(":");
  const key = SORT_KEYS.includes(keyRaw as AssetSortKey)
    ? (keyRaw as AssetSortKey)
    : DEFAULT_SORT.key;
  const direction: AssetSortState["direction"] =
    dirRaw === "asc" ? "asc" : "desc";
  return { key, direction };
}

function parsePageFromSearchParams(sp: URLSearchParams): number {
  const n = Number(sp.get("page") ?? "1");
  return Number.isFinite(n) && n >= 1 ? Math.floor(n) : 1;
}

// ---------------------------------------------------------------------------
// AssetsClient
// ---------------------------------------------------------------------------

export interface AssetsClientProps {
  projectId: string;
  /**
   * Whether the current viewer may edit notes. Defaults to true; backend
   * enforces authority independently (defence-in-depth only). A future plan
   * can wire this to a layout-provided role context (matches EASM drawer pattern).
   */
  canEditNote?: boolean;
}

export default function AssetsClient({
  projectId,
  canEditNote = true,
}: AssetsClientProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const filters = useMemo(
    () => parseFiltersFromSearchParams(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );

  const sort = useMemo(
    () => parseSortFromSearchParams(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );

  const page = useMemo(
    () => parsePageFromSearchParams(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );

  // Summary fetch — 7-bucket map; populated on mount + on filters change.
  const [summary, setSummary] = useState<AssetSummaryMap | null>(null);

  // List fetch — paginated asset rows.
  const [rows, setRows] = useState<AssetRow[]>([]);
  const [listTotal, setListTotal] = useState(0);
  const [listLoading, setListLoading] = useState(true);

  // Filter options — distinct types + modules discovered across ALL assets
  // for this project (unfiltered snapshot on mount). Scans = project's EASM
  // scan history. Null = still loading, [] = loaded + empty.
  const [availableTypes, setAvailableTypes] = useState<string[] | null>(null);
  const [availableModules, setAvailableModules] = useState<string[] | null>(
    null,
  );
  const [availableScans, setAvailableScans] = useState<
    { id: string; label: string }[] | null
  >(null);

  // Drawer/asset-id param — controlled by URL so refresh preserves state.
  const drawerAssetId = searchParams.get("asset") || null;

  // Derived total from summary — sum of all bucket counts.
  const total = useMemo(() => {
    if (!summary) return 0;
    return Object.values(summary).reduce((acc, b) => acc + (b?.count ?? 0), 0);
  }, [summary]);

  // Filter-option snapshot: fetch once per project (no filters, max limit).
  // Derives distinct bbot_event_type and flattened modules from the rows.
  // Runs independently of the filtered list fetch so turning on a type
  // filter doesn't empty the option list.
  useEffect(() => {
    let cancelled = false;
    const url = `/api/projects/${projectId}/assets?limit=500&offset=0`;
    fetch(url, { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`options ${res.status}`);
        const json = (await res.json()) as AssetListResponse;
        if (cancelled) return;
        const typeSet = new Set<string>();
        const modSet = new Set<string>();
        for (const row of json.items ?? []) {
          if (row.bbot_event_type) typeSet.add(row.bbot_event_type);
          for (const m of row.modules ?? []) if (m) modSet.add(m);
        }
        setAvailableTypes([...typeSet].sort());
        setAvailableModules([...modSet].sort());
      })
      .catch(() => {
        if (!cancelled) {
          setAvailableTypes([]);
          setAvailableModules([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Scan list — dropdown source for the Scan filter.
  useEffect(() => {
    let cancelled = false;
    const url = `/api/projects/${projectId}/easm/scans`;
    fetch(url, { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`scans ${res.status}`);
        const json = (await res.json()) as {
          items?: Array<{
            id: string;
            scan_mode?: string;
            started_at?: string;
            status?: string;
          }>;
        };
        if (cancelled) return;
        const items = json.items ?? [];
        setAvailableScans(
          items.map((s) => ({
            id: s.id,
            label: `${(s.scan_mode ?? "?").toUpperCase()} · ${
              s.started_at ? new Date(s.started_at).toLocaleString() : s.id.slice(0, 8)
            } · ${s.status ?? ""}`,
          })),
        );
      })
      .catch(() => {
        if (!cancelled) setAvailableScans([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Fetch summary whenever filters change.
  useEffect(() => {
    let cancelled = false;
    const qs = buildSearchParams(filters).toString();
    const url =
      `/api/projects/${projectId}/assets/summary` + (qs ? `?${qs}` : "");
    fetch(url, { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`summary ${res.status}`);
        const json = (await res.json()) as AssetSummaryResponse;
        if (!cancelled) setSummary(json.buckets ?? {});
      })
      .catch(() => {
        if (!cancelled) setSummary({});
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, filters]);

  // Fetch list whenever filters, sort, or page change.
  useEffect(() => {
    let cancelled = false;
    setListLoading(true);
    const params = buildSearchParams(filters);
    // Backend accepts limit + offset (not page/page_size) and does not yet
    // honour a server-side sort param — sort is applied client-side via
    // displayedRows. See backend/app/routers/assets.py list endpoint.
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String((page - 1) * PAGE_SIZE));
    const url = `/api/projects/${projectId}/assets?${params.toString()}`;
    fetch(url, { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`list ${res.status}`);
        const json = (await res.json()) as AssetListResponse;
        if (!cancelled) {
          setRows(Array.isArray(json.items) ? json.items : []);
          setListTotal(typeof json.total === "number" ? json.total : 0);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRows([]);
          setListTotal(0);
        }
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, filters, sort, page]);

  // --- URL sync helpers ---------------------------------------------------

  const pushFilters = useCallback(
    (next: AssetFilters) => {
      const params = buildSearchParams(next);
      // Preserve sort + drawer across filter edits; reset page to 1.
      params.set("sort", `${sort.key}:${sort.direction}`);
      const assetId = searchParams.get("asset");
      if (assetId) params.set("asset", assetId);
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams, sort],
  );

  const clearFilters = useCallback(() => {
    const assetId = searchParams.get("asset");
    const qs = assetId ? `?asset=${encodeURIComponent(assetId)}` : "";
    router.replace(`${pathname}${qs}`, { scroll: false });
  }, [pathname, router, searchParams]);

  const pushSort = useCallback(
    (next: AssetSortState) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("sort", `${next.key}:${next.direction}`);
      params.delete("page"); // reset to page 1 on sort change
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const pushPage = useCallback(
    (nextPage: number) => {
      const params = new URLSearchParams(searchParams.toString());
      if (nextPage <= 1) params.delete("page");
      else params.set("page", String(nextPage));
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const openDrawer = useCallback(
    (assetId: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("asset", assetId);
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const closeDrawer = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("asset");
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [pathname, router, searchParams]);

  // Summary card click → sets (or clears) the type filter for that bucket.
  const activeBucket = useMemo<string | null>(() => {
    // Single-bucket-active = exact match between current type filter and a bucket's types.
    for (const key of BUCKET_ORDER) {
      const bucketTypes = BUCKET_TYPE_MAP[key];
      if (key === "OTHER") continue; // OTHER is catch-all; active-state not meaningful
      if (
        bucketTypes.length === filters.type.length &&
        bucketTypes.every((t) => filters.type.includes(t))
      ) {
        return key;
      }
    }
    return null;
  }, [filters.type]);

  const onBucketClick = useCallback(
    (bucketKey: string) => {
      const bucketTypes = BUCKET_TYPE_MAP[bucketKey] ?? [];
      const isActive = activeBucket === bucketKey;
      pushFilters({
        ...filters,
        type: isActive ? [] : [...bucketTypes],
      });
    },
    [activeBucket, filters, pushFilters],
  );

  // --- Export --------------------------------------------------------------

  const exportHref = useCallback(
    (format: "csv" | "json") => {
      const qs = buildSearchParams(filters).toString();
      const suffix = qs ? `&${qs}` : "";
      return `/api/projects/${projectId}/assets/export?format=${format}${suffix}`;
    },
    [filters, projectId],
  );

  const exportDisabled = total === 0;

  function onExport(format: "csv" | "json") {
    if (exportDisabled) return;
    window.location.href = exportHref(format);
  }

  // --- Render --------------------------------------------------------------

  const hasFilters = isAnyFilterActive(filters);
  // Empty-state variant: project-no-findings vs filtered-zero.
  // Heuristic: when no filters are active AND total === 0 → project truly has no findings.
  // When filters are active AND total === 0 → filters match nothing.
  const showEmptyNoFindings = !hasFilters && total === 0 && summary !== null;
  const showEmptyFiltered = hasFilters && total === 0 && summary !== null;
  // Table is only rendered when at least one asset could match (total > 0 OR still loading).
  const showTable = summary === null || total > 0;

  const exportButton = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="default"
          size="sm"
          disabled={exportDisabled}
          aria-label="Export"
        >
          Export
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => onExport("csv")}>
          Export as CSV
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => onExport("json")}>
          Export as JSON
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );

  return (
    <div className="flex flex-col gap-8">
      {/* Heading row */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-[22px] font-medium">Assets</h1>
          <p className="text-[12px] text-muted-foreground">
            BBOT discovery surface for this project.
          </p>
        </div>
        <div className="shrink-0">
          {exportDisabled ? (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  {/* Span wrapper — disabled buttons don't fire pointer events,
                      so the tooltip listens on a wrapping span per Radix docs. */}
                  <span className="inline-block">{exportButton}</span>
                </TooltipTrigger>
                <TooltipContent>
                  No assets to export. Adjust filters or run a scan.
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          ) : (
            exportButton
          )}
        </div>
      </div>

      {/* Summary cards */}
      <AssetSummaryCards
        summary={summary}
        activeBucket={activeBucket}
        onBucketClick={onBucketClick}
      />

      {/* Filter bar */}
      <AssetsFilterBar
        filters={filters}
        onChange={pushFilters}
        onClear={clearFilters}
        availableTypes={availableTypes}
        availableModules={availableModules}
        availableScans={availableScans}
      />

      {/* AssetsTable — wired in 05b */}
      {showTable && (
        <AssetsTable
          rows={rows}
          loading={listLoading}
          sort={sort}
          onSortChange={pushSort}
          onRowClick={openDrawer}
          pagination={{
            page,
            pageSize: PAGE_SIZE,
            total: listTotal,
            onPageChange: pushPage,
          }}
        />
      )}

      {/* AssetDetailDrawer — mounted when ?asset= is set (wired in 05b) */}
      <AssetDetailDrawer
        projectId={projectId}
        assetId={drawerAssetId}
        onClose={closeDrawer}
        canEditNote={canEditNote}
      />

      {/* Empty states — UI-SPEC §Empty States */}
      {showEmptyFiltered && (
        <div
          className="flex flex-col items-center justify-center py-16 gap-2"
          data-testid="assets-empty-filtered"
        >
          <h2 className="text-[22px] font-medium">No assets match these filters.</h2>
          <p className="text-muted-foreground text-[16px]">
            Clear filters or widen the date range to see more.
          </p>
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            Clear filters
          </Button>
        </div>
      )}

      {showEmptyNoFindings && (
        <div
          className="flex flex-col items-center justify-center py-16 gap-2"
          data-testid="assets-empty-no-findings"
        >
          <h2 className="text-[22px] font-medium">No assets yet.</h2>
          <p className="text-muted-foreground text-[16px]">
            Run an EASM scan to populate this project&apos;s asset surface.
          </p>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => router.push(`/projects/${projectId}/easm`)}
          >
            Go to EASM dashboard
          </Button>
        </div>
      )}
    </div>
  );
}
