"use client";

import type { FilterPreset } from "@/app/api-client";

type Props = {
  value: string[];
  options: FilterPreset[];
  onChange: (names: string[]) => void;
  loading: boolean;
};

/**
 * Custom multi-select for filter presets.
 * No ScrollArea shadcn component — uses plain div + overflow-y-auto.
 * Renders three states: loading, empty, or a scrollable checkbox list.
 */
export function PresetMultiSelect({ value, options, onChange, loading }: Props) {
  if (loading) {
    return (
      <span className="text-xs text-muted-foreground">Loading presets…</span>
    );
  }

  if (options.length === 0) {
    return (
      <span className="text-xs text-muted-foreground">
        No presets yet — save a filter preset on the Events page first.
      </span>
    );
  }

  function toggle(name: string, checked: boolean) {
    onChange(checked ? [...value, name] : value.filter((x) => x !== name));
  }

  return (
    <div
      role="group"
      aria-label="Bound presets"
      className="max-h-48 overflow-y-auto border rounded p-2"
    >
      {options.map((p) => (
        <label
          key={p.name}
          className="flex items-center gap-2 py-1 cursor-pointer hover:bg-card px-2 rounded"
        >
          <input
            type="checkbox"
            checked={value.includes(p.name)}
            onChange={(e) => toggle(p.name, e.target.checked)}
          />
          <span className="text-sm">{p.name}</span>
        </label>
      ))}
    </div>
  );
}
