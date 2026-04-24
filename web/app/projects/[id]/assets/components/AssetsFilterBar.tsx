"use client";

/**
 * AssetsFilterBar — Phase 12.1 plan 12.1-05a (UI-SPEC §Surface 4).
 *
 * 9 controls: Type multi-select, Scope multi-select, Stale single-select,
 * Module multi-select, First-seen + Last-seen date ranges, Scan select,
 * Search input (submit-on-Enter), Clear filters ghost button.
 *
 * Multi-select trigger label formulas (UI-SPEC Copywriting Contract):
 *   0 selected → "All types" / "All scopes" / "All modules"
 *   1 selected → that label
 *   2+ selected → "{first} +{N-1}"
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type StaleFilterValue = "show" | "hide" | "only";

/**
 * Stale filter option labels (UI-SPEC Copywriting Contract, byte-exact).
 * Keys are the value; values are the label rendered in the Select.
 */
export const STALE_OPTION_LABELS: Record<StaleFilterValue, string> = {
  show: "Show all",
  hide: "Hide stale",
  only: "Only stale",
};

export interface AssetFilters {
  type: string[];
  scope: string[];
  stale: StaleFilterValue;
  module: string[];
  first_seen_from: string;
  first_seen_to: string;
  last_seen_from: string;
  last_seen_to: string;
  scan_id: string;
  search: string;
}

/** One entry per option in the Scan <Select>. */
export interface ScanOption {
  id: string;
  label: string;
}

const SCOPE_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "in_scope", label: "In scope" },
  { value: "out_of_scope", label: "Out of scope" },
  { value: "unscoped", label: "Unscoped" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Multi-select trigger label — UI-SPEC Copywriting Contract byte-exact.
 *   0 → defaultLabel (e.g. "All types")
 *   1 → the selected label (or value if labelMap missing)
 *   2+ → "{first} +{N-1}"
 */
function triggerLabel(
  selected: string[],
  defaultLabel: string,
  labelMap?: Record<string, string>,
): string {
  if (selected.length === 0) return defaultLabel;
  const first = labelMap?.[selected[0]] ?? selected[0];
  if (selected.length === 1) return first;
  return `${first} +${selected.length - 1}`;
}

function toggleArrayValue(arr: string[], value: string): string[] {
  return arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value];
}

function anyFilterActive(f: AssetFilters): boolean {
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

// ---------------------------------------------------------------------------
// AssetsFilterBar
// ---------------------------------------------------------------------------

export interface AssetsFilterBarProps {
  filters: AssetFilters;
  onChange: (next: AssetFilters) => void;
  onClear: () => void;
  /** null = still loading the option list; [] = loaded but empty. */
  availableTypes: string[] | null;
  availableModules: string[] | null;
  availableScans: ScanOption[] | null;
  /** Error advisory (top-of-page) when option lists failed to load. */
  filterOptionsErrored?: boolean;
  onRetryFilterOptions?: () => void;
}

// Sentinel for "no filter applied" — Radix Select forbids empty string values.
const ALL_SCANS = "__all__";

export function AssetsFilterBar({
  filters,
  onChange,
  onClear,
  availableTypes,
  availableModules,
  availableScans,
  filterOptionsErrored,
  onRetryFilterOptions,
}: AssetsFilterBarProps) {
  // Local search buffer so typing doesn't round-trip through URL on every keystroke.
  const [searchDraft, setSearchDraft] = useState<string>(filters.search);

  const typesLoading = availableTypes === null;
  const modulesLoading = availableModules === null;
  const scansLoading = availableScans === null;

  function patch(partial: Partial<AssetFilters>) {
    onChange({ ...filters, ...partial });
  }

  const scopeLabelMap: Record<string, string> = Object.fromEntries(
    SCOPE_OPTIONS.map((o) => [o.value, o.label]),
  );

  const showClear = anyFilterActive(filters);

  return (
    <div className="flex flex-col gap-2">
      {filterOptionsErrored && (
        <div
          className="text-[12px] text-muted-foreground flex items-center gap-2"
          data-testid="assets-filter-options-error"
        >
          <span>
            Filter options could not be loaded. Showing unfiltered results.
          </span>
          {onRetryFilterOptions && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onRetryFilterOptions}
              aria-label="Retry"
            >
              Retry
            </Button>
          )}
        </div>
      )}
      <div
        className="flex flex-wrap gap-4 items-center py-4 border-b border-border"
        data-testid="assets-filter-bar"
      >
        {/* Type multi-select */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              disabled={typesLoading}
              aria-label="Filter by type"
              data-testid="assets-filter-type-trigger"
            >
              {typesLoading
                ? "Loading…"
                : triggerLabel(filters.type, "All types")}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="max-h-72 overflow-y-auto">
            {(availableTypes ?? []).map((t) => (
              <DropdownMenuCheckboxItem
                key={t}
                checked={filters.type.includes(t)}
                onCheckedChange={() =>
                  patch({ type: toggleArrayValue(filters.type, t) })
                }
                onSelect={(e) => e.preventDefault()}
              >
                {t}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Scope multi-select */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              aria-label="Filter by scope"
              data-testid="assets-filter-scope-trigger"
            >
              {triggerLabel(filters.scope, "All scopes", scopeLabelMap)}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {SCOPE_OPTIONS.map((opt) => (
              <DropdownMenuCheckboxItem
                key={opt.value}
                checked={filters.scope.includes(opt.value)}
                onCheckedChange={() =>
                  patch({ scope: toggleArrayValue(filters.scope, opt.value) })
                }
                onSelect={(e) => e.preventDefault()}
              >
                {opt.label}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Stale single-select */}
        <Select
          value={filters.stale}
          onValueChange={(v) => patch({ stale: v as StaleFilterValue })}
        >
          <SelectTrigger
            className="h-9 w-[140px]"
            aria-label="Filter by stale state"
            data-testid="assets-filter-stale-trigger"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="show">{STALE_OPTION_LABELS.show}</SelectItem>
            <SelectItem value="hide">{STALE_OPTION_LABELS.hide}</SelectItem>
            <SelectItem value="only">{STALE_OPTION_LABELS.only}</SelectItem>
          </SelectContent>
        </Select>

        {/* Module multi-select */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              disabled={modulesLoading}
              aria-label="Filter by module"
              data-testid="assets-filter-module-trigger"
            >
              {modulesLoading
                ? "Loading…"
                : triggerLabel(filters.module, "All modules")}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="max-h-72 overflow-y-auto">
            {(availableModules ?? []).map((m) => (
              <DropdownMenuCheckboxItem
                key={m}
                checked={filters.module.includes(m)}
                onCheckedChange={() =>
                  patch({ module: toggleArrayValue(filters.module, m) })
                }
                onSelect={(e) => e.preventDefault()}
              >
                {m}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* First-seen range */}
        <div className="flex items-center gap-1">
          <label
            htmlFor="first-seen-from"
            className="text-[12px] text-muted-foreground"
          >
            First seen
          </label>
          <Input
            id="first-seen-from"
            type="date"
            aria-label="First seen from"
            className="h-9 w-[140px]"
            value={filters.first_seen_from}
            onChange={(e) => patch({ first_seen_from: e.target.value })}
          />
          <span className="text-[12px] text-muted-foreground">to</span>
          <Input
            type="date"
            aria-label="First seen to"
            className="h-9 w-[140px]"
            value={filters.first_seen_to}
            onChange={(e) => patch({ first_seen_to: e.target.value })}
          />
        </div>

        {/* Last-seen range */}
        <div className="flex items-center gap-1">
          <label
            htmlFor="last-seen-from"
            className="text-[12px] text-muted-foreground"
          >
            Last seen
          </label>
          <Input
            id="last-seen-from"
            type="date"
            aria-label="Last seen from"
            className="h-9 w-[140px]"
            value={filters.last_seen_from}
            onChange={(e) => patch({ last_seen_from: e.target.value })}
          />
          <span className="text-[12px] text-muted-foreground">to</span>
          <Input
            type="date"
            aria-label="Last seen to"
            className="h-9 w-[140px]"
            value={filters.last_seen_to}
            onChange={(e) => patch({ last_seen_to: e.target.value })}
          />
        </div>

        {/* Scan single-select */}
        <Select
          value={filters.scan_id === "" ? ALL_SCANS : filters.scan_id}
          onValueChange={(v) =>
            patch({ scan_id: v === ALL_SCANS ? "" : v })
          }
          disabled={scansLoading}
        >
          <SelectTrigger
            className="h-9 w-[220px]"
            aria-label="Filter by scan"
            data-testid="assets-filter-scan-trigger"
          >
            <SelectValue placeholder={scansLoading ? "Loading…" : "All scans"} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_SCANS}>All scans</SelectItem>
            {(availableScans ?? []).map((s) => (
              <SelectItem key={s.id} value={s.id}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Search input — submit on Enter */}
        <Input
          type="search"
          placeholder="Search target…"
          aria-label="Search target"
          data-testid="assets-filter-search"
          className="h-9 w-[220px]"
          value={searchDraft}
          onChange={(e) => setSearchDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              patch({ search: searchDraft });
            }
          }}
        />

        {/* Clear filters — visible only when at least one filter is active. */}
        {showClear && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSearchDraft("");
              onClear();
            }}
            aria-label="Clear filters"
            data-testid="assets-filter-clear"
          >
            Clear filters
          </Button>
        )}
      </div>
    </div>
  );
}
