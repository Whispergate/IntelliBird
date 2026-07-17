"use client";

/**
 * FindingsFilterBar — (UI-SPEC §Surface 3 §Filter bar).
 *
 * Four shadcn Select dropdowns inline:
 *   Type | Module | Severity | Lifecycle
 * Plus a "Show dismissed" checkbox that toggles include_dismissed.
 *
 * Module options are populated from /api/easm/safelist (passed as prop).
 * All other option lists are static per UI-SPEC.
 */

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { FindingsFilters, LifecycleStatus, Severity } from "./lib/api";

// UI-SPEC §Surface 3 §Filter bar — exact option lists
const TYPE_OPTIONS = [
  "DNS_NAME",
  "IP_ADDRESS",
  "OPEN_PORT",
  "URL",
  "FINDING",
  "VULNERABILITY",
  "SUBDOMAIN_TAKEOVER_CANDIDATE",
  "TECHNOLOGY",
] as const;

const SEVERITY_OPTIONS: ReadonlyArray<{ value: Severity; label: string }> = [
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];

const LIFECYCLE_OPTIONS: ReadonlyArray<{
  value: LifecycleStatus;
  label: string;
}> = [
  { value: "new", label: "New" },
  { value: "confirmed", label: "Confirmed" },
  { value: "dismissed", label: "Dismissed" },
  { value: "watchlist", label: "Watchlist" },
];

interface FindingsFilterBarProps {
  filters: FindingsFilters;
  onChange: (updated: FindingsFilters) => void;
  availableModules: string[];
}

export function FindingsFilterBar({
  filters,
  onChange,
  availableModules,
}: FindingsFilterBarProps) {
  // Sentinel for "no filter applied" — Radix Select forbids empty string values.
  const ALL = "__all__";

  function patch(partial: Partial<FindingsFilters>) {
    onChange({ ...filters, ...partial, offset: 0 });
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* Type */}
      <Select
        value={filters.type ?? ALL}
        onValueChange={(v) => patch({ type: v === ALL ? undefined : v })}
      >
        <SelectTrigger className="h-9 w-[200px]">
          <SelectValue placeholder="All types" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All types</SelectItem>
          {TYPE_OPTIONS.map((t) => (
            <SelectItem key={t} value={t}>
              {t}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Module */}
      <Select
        value={filters.module ?? ALL}
        onValueChange={(v) => patch({ module: v === ALL ? undefined : v })}
      >
        <SelectTrigger className="h-9 w-[180px]">
          <SelectValue placeholder="All modules" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All modules</SelectItem>
          {availableModules.map((m) => (
            <SelectItem key={m} value={m}>
              {m}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Severity */}
      <Select
        value={filters.severity ?? ALL}
        onValueChange={(v) =>
          patch({ severity: v === ALL ? undefined : (v as Severity) })
        }
      >
        <SelectTrigger className="h-9 w-[160px]">
          <SelectValue placeholder="All severities" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All severities</SelectItem>
          {SEVERITY_OPTIONS.map((s) => (
            <SelectItem key={s.value} value={s.value}>
              {s.label}
            </SelectItem>
          ))}
          <SelectItem value="none">None</SelectItem>
        </SelectContent>
      </Select>

      {/* Lifecycle */}
      <Select
        value={filters.lifecycle ?? ALL}
        onValueChange={(v) =>
          patch({ lifecycle: v === ALL ? undefined : (v as LifecycleStatus) })
        }
      >
        <SelectTrigger className="h-9 w-[160px]">
          <SelectValue placeholder="All statuses" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All statuses</SelectItem>
          {LIFECYCLE_OPTIONS.map((l) => (
            <SelectItem key={l.value} value={l.value}>
              {l.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Show dismissed toggle */}
      <div className="flex items-center gap-2 ml-2">
        <Checkbox
          id="show-dismissed"
          checked={filters.include_dismissed ?? false}
          onCheckedChange={(checked) =>
            patch({ include_dismissed: checked === true })
          }
        />
        <Label htmlFor="show-dismissed" className="text-sm cursor-pointer">
          Show dismissed
        </Label>
      </div>
    </div>
  );
}
