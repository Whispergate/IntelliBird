"use client";

/**
 * CompareTable - shared presentational table reused 3× on /projects/compare.
 *
 * Renders one section (Shared actors / Shared techniques / Shared IOCs) with:
 *   - Heading with row count in parentheses (UI-SPEC lock)
 *   - Empty-state muted single line when rows.length === 0 (copy from caller)
 *   - 500-row cap caption when rows.length === CAP (CompareTable doesn't know
 *     the cap - caller passes `capReached` explicitly so the table stays agnostic)
 *
 * Row rendering is delegated to `renderRow(row, idx)` so the three call-sites
 * can each render their specific shape (string for actors/techniques,
 * `{kind, value}` for IOCs) with their own link + copy affordances.
 *
 * Also exports `copyToClipboard(value)` - a thin wrapper around
 * navigator.clipboard.writeText that pops a sonner toast on success/failure.
 * Kept here so ProjectCompareClient + any future call-site share one behaviour.
 */
import type { ReactNode } from "react";
import { toast } from "sonner";

export type CompareItem =
  | { kind: "actor"; value: string }
  | { kind: "technique"; value: string }
  | {
      kind: "ioc";
      kind_label: "ip" | "domain" | "hash";
      value: string;
    };

export function CompareTable<T>({
  heading,
  rows,
  emptyCopy,
  capReached,
  renderRow,
}: {
  heading: string;
  rows: readonly T[];
  emptyCopy: string;
  capReached: boolean;
  renderRow: (row: T, idx: number) => ReactNode;
}) {
  return (
    <section>
      <h2 className="brand-heading mb-2 text-foreground">
        {heading} ({rows.length})
      </h2>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground py-4">{emptyCopy}</p>
      ) : (
        <>
          <table className="w-full border-collapse">
            <tbody>{rows.map((row, i) => renderRow(row, i))}</tbody>
          </table>
          {capReached && (
            <p className="text-xs text-muted-foreground mt-2">
              Showing 500 - narrow project scope to see all.
            </p>
          )}
        </>
      )}
    </section>
  );
}

/**
 * Copy a string to the clipboard, surfacing success/failure as a toast.
 * Non-secure-context (HTTP, legacy browser) → clipboard API unavailable → toast.error.
 */
export function copyToClipboard(value: string) {
  if (
    typeof navigator === "undefined" ||
    !navigator.clipboard ||
    typeof navigator.clipboard.writeText !== "function"
  ) {
    toast.error("Could not copy to clipboard.");
    return;
  }
  navigator.clipboard.writeText(value).then(
    () => toast.success(`Copied ${value}`),
    () => toast.error("Could not copy to clipboard."),
  );
}
