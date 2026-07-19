"use client";

import { X } from "lucide-react";
import type { EventsQuery, TlpName } from "@/app/api-client";

type Props = {
  activeFilters: EventsQuery;
  onRemove: (key: keyof EventsQuery, value?: string) => void;
};

const CHIP_BASE =
  "inline-flex items-center gap-1 h-7 px-2 rounded-full border border-border brand-caption bg-muted text-foreground cursor-pointer hover:opacity-80 transition-opacity";
const CHIP_ACTIVE_BORDER = "border-[var(--brand-signal)]";

function Chip({
  label,
  ariaLabel,
  onRemove,
}: {
  label: string;
  ariaLabel: string;
  onRemove: () => void;
}) {
  return (
    <button
      type="button"
      role="button"
      aria-label={ariaLabel}
      className={`${CHIP_BASE} ${CHIP_ACTIVE_BORDER}`}
      onClick={onRemove}
    >
      <span>{label}</span>
      <X className="h-3 w-3 shrink-0" aria-hidden="true" />
    </button>
  );
}

export function FilterChips({ activeFilters, onRemove }: Props) {
  const chips: { label: string; ariaLabel: string; remove: () => void }[] = [];

  // TLP chips (array)
  for (const tlp of activeFilters.tlp ?? []) {
    chips.push({
      label: `TLP: ${tlp}`,
      ariaLabel: `Remove tlp filter: ${tlp}`,
      remove: () => onRemove("tlp", tlp),
    });
  }

  // source chips (array)
  for (const src of activeFilters.source ?? []) {
    chips.push({
      label: `Source: ${src}`,
      ariaLabel: `Remove source filter: ${src}`,
      remove: () => onRemove("source", src),
    });
  }

  // tag chips (array)
  for (const tag of activeFilters.tag ?? []) {
    chips.push({
      label: `Tag: ${tag}`,
      ariaLabel: `Remove tag filter: ${tag}`,
      remove: () => onRemove("tag", tag),
    });
  }

  // source_type chips (array)
  for (const st of activeFilters.source_type ?? []) {
    chips.push({
      label: `Type: ${st}`,
      ariaLabel: `Remove source_type filter: ${st}`,
      remove: () => onRemove("source_type", st),
    });
  }

  // observed_from scalar
  if (activeFilters.observed_from) {
    const val = activeFilters.observed_from;
    chips.push({
      label: `From: ${val}`,
      ariaLabel: `Remove observed_from filter: ${val}`,
      remove: () => onRemove("observed_from"),
    });
  }

  // observed_to scalar
  if (activeFilters.observed_to) {
    const val = activeFilters.observed_to;
    chips.push({
      label: `To: ${val}`,
      ariaLabel: `Remove observed_to filter: ${val}`,
      remove: () => onRemove("observed_to"),
    });
  }

  if (chips.length === 0) return null;

  return (
    <div
      className="flex flex-wrap gap-2"
      aria-label="Active filters"
      role="group"
    >
      {chips.map((chip, i) => (
        <Chip
          key={`${chip.label}-${i}`}
          label={chip.label}
          ariaLabel={chip.ariaLabel}
          onRemove={chip.remove}
        />
      ))}
    </div>
  );
}
