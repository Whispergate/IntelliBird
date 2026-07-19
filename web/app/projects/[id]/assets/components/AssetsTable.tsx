"use client";

/**
 * AssetsTable - (UI-SPEC §Surface 5).
 *
 * 9-column locked layout:
 *   Type | Target | Scope | First seen | Last seen | Scans | Modules | Stale | Actions
 *
 * - Default sort: last_seen DESC.
 * - Row click / Enter / Space → onRowClick(asset_id); URL sync handled by parent.
 * - 50 per page pagination controls at bottom-right.
 * - Scope chip tokens (UI-SPEC Color):
 *     in_scope      → bg-teal-900/40 text-teal-300
 *     out_of_scope  → border border-destructive text-destructive bg-transparent
 *     unscoped      → bg-muted text-muted-foreground
 * - Stale pill: bg-muted text-muted-foreground (NEVER signal-amber).
 */

import { ChevronDown, ChevronRight, ChevronUp } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Types - mirror backend schema (12.1-02); generated api-client lands in 12.1-06.
// ---------------------------------------------------------------------------

export type AssetScope = "in_scope" | "out_of_scope" | "unscoped";

export interface AssetRow {
  asset_id: string;
  bbot_event_type: string;
  canonical_target: string;
  scope: AssetScope;
  first_seen: string; // ISO
  last_seen: string; // ISO
  scan_count: number;
  modules: string[];
  stale: boolean;
}

export type AssetSortKey =
  | "type"
  | "target"
  | "first_seen"
  | "last_seen"
  | "scan_count";

export interface AssetSortState {
  key: AssetSortKey;
  direction: "asc" | "desc";
}

export interface AssetsTablePagination {
  page: number; // 1-indexed
  pageSize: number;
  total: number;
  onPageChange: (nextPage: number) => void;
}

export interface AssetsTableProps {
  rows: AssetRow[];
  loading?: boolean;
  sort: AssetSortState;
  onSortChange: (next: AssetSortState) => void;
  onRowClick: (assetId: string) => void;
  pagination: AssetsTablePagination;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DATE_FMT = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
});

function formatDate(iso: string): string {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "\u2014";
  return DATE_FMT.format(d);
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + "\u2026";
}

// ---------------------------------------------------------------------------
// Scope chip - locked tokens per UI-SPEC §Color
// ---------------------------------------------------------------------------

function ScopeChip({ scope }: { scope: AssetScope }) {
  if (scope === "in_scope") {
    return (
      <Badge
        className="bg-teal-900/40 text-teal-300 hover:bg-teal-900/40"
        title="Target matches at least one active scope row."
      >
        in scope
      </Badge>
    );
  }
  if (scope === "out_of_scope") {
    return (
      <Badge
        className="border border-destructive text-destructive bg-transparent"
        title="Target is outside all active scope rows for this project."
      >
        out of scope
      </Badge>
    );
  }
  return (
    <Badge
      className="bg-muted text-muted-foreground hover:bg-muted"
      title="Target cannot be matched to any scope row (e.g. technology or email without a resolvable host)."
    >
      unscoped
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Sort chevron
// ---------------------------------------------------------------------------

function SortChevron({
  columnKey,
  sort,
}: {
  columnKey: AssetSortKey;
  sort: AssetSortState;
}) {
  if (sort.key !== columnKey) {
    return (
      <ChevronDown
        aria-hidden
        className="inline h-3 w-3 ml-1 text-muted-foreground/40"
      />
    );
  }
  return sort.direction === "asc" ? (
    <ChevronUp aria-hidden className="inline h-3 w-3 ml-1 text-foreground" />
  ) : (
    <ChevronDown aria-hidden className="inline h-3 w-3 ml-1 text-foreground" />
  );
}

function toggleSort(
  key: AssetSortKey,
  current: AssetSortState,
): AssetSortState {
  if (current.key !== key) {
    // New column: first click uses sensible default (desc for dates/counts, asc for text).
    const direction: AssetSortState["direction"] =
      key === "type" || key === "target" ? "asc" : "desc";
    return { key, direction };
  }
  return {
    key,
    direction: current.direction === "asc" ? "desc" : "asc",
  };
}

// ---------------------------------------------------------------------------
// Modules cell - truncate at 2, tooltip with full list
// ---------------------------------------------------------------------------

function ModulesCell({ modules }: { modules: string[] }) {
  if (modules.length === 0) {
    return <span className="text-muted-foreground">\u2014</span>;
  }
  if (modules.length <= 2) {
    return (
      <span className="text-[12px] truncate">{modules.join(", ")}</span>
    );
  }
  const shown = modules.slice(0, 2).join(", ");
  const more = modules.length - 2;
  const fullList = modules.join(", ");
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="text-[12px] truncate">
            {shown} +{more} more
          </span>
        </TooltipTrigger>
        <TooltipContent>{fullList}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// Pagination text
// ---------------------------------------------------------------------------

function buildPaginationText(
  page: number,
  pageSize: number,
  total: number,
): string {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return `Page ${page} of ${totalPages} \u2014 ${pageSize} per page`;
}

// ---------------------------------------------------------------------------
// AssetsTable
// ---------------------------------------------------------------------------

const SKELETON_ROWS = 5;

export function AssetsTable({
  rows,
  loading = false,
  sort,
  onSortChange,
  onRowClick,
  pagination,
}: AssetsTableProps) {
  const { page, pageSize, total, onPageChange } = pagination;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const prevDisabled = page <= 1;
  const nextDisabled = page >= totalPages;

  const handleHeaderClick = (key: AssetSortKey) => () => {
    onSortChange(toggleSort(key, sort));
  };

  const headers = (
    <TableHeader>
      <TableRow>
        <TableHead
          style={{ width: 160 }}
          className="cursor-pointer select-none"
          onClick={handleHeaderClick("type")}
          aria-sort={
            sort.key === "type"
              ? sort.direction === "asc"
                ? "ascending"
                : "descending"
              : "none"
          }
        >
          Type
          <SortChevron columnKey="type" sort={sort} />
        </TableHead>
        <TableHead
          className="cursor-pointer select-none"
          style={{ minWidth: 320 }}
          onClick={handleHeaderClick("target")}
          aria-sort={
            sort.key === "target"
              ? sort.direction === "asc"
                ? "ascending"
                : "descending"
              : "none"
          }
        >
          Target
          <SortChevron columnKey="target" sort={sort} />
        </TableHead>
        <TableHead style={{ width: 120 }}>Scope</TableHead>
        <TableHead
          style={{ width: 120 }}
          className="cursor-pointer select-none"
          onClick={handleHeaderClick("first_seen")}
          aria-sort={
            sort.key === "first_seen"
              ? sort.direction === "asc"
                ? "ascending"
                : "descending"
              : "none"
          }
        >
          First seen
          <SortChevron columnKey="first_seen" sort={sort} />
        </TableHead>
        <TableHead
          style={{ width: 120 }}
          className="cursor-pointer select-none"
          onClick={handleHeaderClick("last_seen")}
          aria-sort={
            sort.key === "last_seen"
              ? sort.direction === "asc"
                ? "ascending"
                : "descending"
              : "none"
          }
        >
          Last seen
          <SortChevron columnKey="last_seen" sort={sort} />
        </TableHead>
        <TableHead
          style={{ width: 72 }}
          className="cursor-pointer select-none text-right"
          onClick={handleHeaderClick("scan_count")}
          aria-sort={
            sort.key === "scan_count"
              ? sort.direction === "asc"
                ? "ascending"
                : "descending"
              : "none"
          }
        >
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  Scans
                  <SortChevron columnKey="scan_count" sort={sort} />
                </span>
              </TooltipTrigger>
              <TooltipContent>
                Distinct scans in which this asset appeared.
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </TableHead>
        <TableHead style={{ width: 160 }}>Modules</TableHead>
        <TableHead style={{ width: 72 }}>Stale</TableHead>
        <TableHead style={{ width: 48 }} aria-label="Open row"></TableHead>
      </TableRow>
    </TableHeader>
  );

  return (
    <div className="bg-card border border-border rounded-md overflow-hidden">
      <Table>
        {headers}
        <TableBody>
          {loading &&
            Array.from({ length: SKELETON_ROWS }).map((_, i) => (
              <TableRow key={`skeleton-${i}`} data-testid="assets-skeleton-row">
                <TableCell colSpan={9}>
                  <div className="animate-pulse bg-muted/40 rounded h-4 w-full" />
                </TableCell>
              </TableRow>
            ))}
          {!loading &&
            rows.map((row) => (
              <TableRow
                key={row.asset_id}
                data-testid="assets-row"
                data-asset-id={row.asset_id}
                role="button"
                tabIndex={0}
                onClick={() => onRowClick(row.asset_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onRowClick(row.asset_id);
                  }
                }}
                className="cursor-pointer hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                style={{ minHeight: 44 }}
              >
                <TableCell>
                  <Badge className="bg-muted text-muted-foreground hover:bg-muted font-medium text-[12px]">
                    {row.bbot_event_type}
                  </Badge>
                </TableCell>
                <TableCell
                  className="font-mono text-[12px] truncate"
                  style={{ maxWidth: "56ch" }}
                  title={row.canonical_target}
                >
                  {truncate(row.canonical_target, 56)}
                </TableCell>
                <TableCell>
                  <ScopeChip scope={row.scope} />
                </TableCell>
                <TableCell className="font-mono text-[12px]">
                  {formatDate(row.first_seen)}
                </TableCell>
                <TableCell className="font-mono text-[12px]">
                  {formatDate(row.last_seen)}
                </TableCell>
                <TableCell className="text-right text-[12px] tabular-nums">
                  {row.scan_count}
                </TableCell>
                <TableCell
                  className="truncate"
                  style={{ maxWidth: 160 }}
                >
                  <ModulesCell modules={row.modules} />
                </TableCell>
                <TableCell>
                  {row.stale ? (
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Badge className="bg-muted text-muted-foreground hover:bg-muted font-medium text-[12px]">
                            Stale
                          </Badge>
                        </TooltipTrigger>
                        <TooltipContent>
                          Not seen in the most recent completed scan.
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  ) : null}
                </TableCell>
                <TableCell className="text-right">
                  <ChevronRight
                    aria-hidden
                    className="h-3 w-3 text-muted-foreground inline"
                  />
                </TableCell>
              </TableRow>
            ))}
        </TableBody>
      </Table>

      {/* Pagination controls */}
      <div className="flex items-center justify-end gap-3 px-4 py-3 border-t border-border">
        <span
          className="text-[12px] text-muted-foreground"
          data-testid="assets-pagination-text"
        >
          {buildPaginationText(page, pageSize, total)}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={prevDisabled}
          onClick={() => onPageChange(page - 1)}
        >
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={nextDisabled}
          onClick={() => onPageChange(page + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
