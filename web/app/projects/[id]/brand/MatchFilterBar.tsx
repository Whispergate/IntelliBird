"use client";

/**
 * MatchFilterBar - (UI-SPEC §Surface 2 §Filter bar).
 *
 * Four controls inline: Severity Select | Source Select | Lifecycle Select +
 * Include-dismissed Switch. Mirrors FindingsFilterBar shape.
 */

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type {
  BrandLifecycleStatus,
  BrandMatchFilters,
  BrandSeverity,
  BrandSource,
} from "./lib/api";

const ALL = "__all__";

const SEVERITY_OPTIONS: ReadonlyArray<{ value: BrandSeverity; label: string }> =
  [
    { value: "high", label: "HIGH" },
    { value: "medium", label: "MEDIUM" },
    { value: "low", label: "LOW" },
  ];

const SOURCE_OPTIONS: ReadonlyArray<{ value: BrandSource; label: string }> = [
  { value: "fts", label: "FTS" },
  { value: "ct_log", label: "CT log" },
  { value: "dnstwist", label: "dnstwist" },
];

const LIFECYCLE_OPTIONS: ReadonlyArray<{
  value: BrandLifecycleStatus;
  label: string;
}> = [
  { value: "new", label: "New" },
  { value: "confirmed", label: "Confirmed" },
  { value: "watchlist", label: "Watchlist" },
];

interface MatchFilterBarProps {
  filters: BrandMatchFilters;
  onChange: (updated: BrandMatchFilters) => void;
}

export function MatchFilterBar({ filters, onChange }: MatchFilterBarProps) {
  function patch(partial: Partial<BrandMatchFilters>) {
    onChange({ ...filters, ...partial });
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* Severity */}
      <Select
        value={filters.severity ?? ALL}
        onValueChange={(v) =>
          patch({ severity: v === ALL ? undefined : (v as BrandSeverity) })
        }
      >
        <SelectTrigger className="h-9 w-[180px]" aria-label="Severity filter">
          <SelectValue placeholder="All severities" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All severities</SelectItem>
          {SEVERITY_OPTIONS.map((s) => (
            <SelectItem key={s.value} value={s.value}>
              {s.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Source */}
      <Select
        value={filters.source ?? ALL}
        onValueChange={(v) =>
          patch({ source: v === ALL ? undefined : (v as BrandSource) })
        }
      >
        <SelectTrigger className="h-9 w-[160px]" aria-label="Source filter">
          <SelectValue placeholder="All sources" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All sources</SelectItem>
          {SOURCE_OPTIONS.map((s) => (
            <SelectItem key={s.value} value={s.value}>
              {s.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Lifecycle */}
      <Select
        value={filters.lifecycle ?? ALL}
        onValueChange={(v) =>
          patch({
            lifecycle: v === ALL ? undefined : (v as BrandLifecycleStatus),
          })
        }
      >
        <SelectTrigger className="h-9 w-[160px]" aria-label="Lifecycle filter">
          <SelectValue placeholder="All statuses" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All</SelectItem>
          {LIFECYCLE_OPTIONS.map((l) => (
            <SelectItem key={l.value} value={l.value}>
              {l.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Include dismissed Switch */}
      <div className="flex items-center gap-2 ml-2">
        <Switch
          id="include-dismissed"
          checked={filters.include_dismissed ?? false}
          onCheckedChange={(checked) =>
            patch({ include_dismissed: checked === true })
          }
          aria-label="Include dismissed"
        />
        <Label htmlFor="include-dismissed" className="text-sm cursor-pointer">
          Include dismissed
        </Label>
      </div>
    </div>
  );
}
