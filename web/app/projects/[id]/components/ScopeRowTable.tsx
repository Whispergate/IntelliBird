"use client";

/**
 * ScopeRowTable — Phase 10 Plan 10-10.
 *
 * Per-scope-type row listing. Columns:
 *   - Value (monospace for ip_range / certificate, default text otherwise)
 *   - Contact (optional contact string or em-dash)
 *   - Exclude   (Switch — disabled read-only in Phase 10; edit via delete+re-add)
 *   - Active test scope (Switch — disabled read-only)
 *   - Intel scope (Switch — disabled read-only)
 *   - Actions (Delete icon button — native window.confirm per UI-SPEC §ScopeRowTable)
 *
 * Scope discipline (plan 10-10 §action note):
 *   "The toggle-disabled approach keeps this plan small; full inline PATCH on
 *    toggle change is a v2.1 follow-up or extended in a later plan. For
 *    Phase 10 the primary editable path is Add/Delete; toggle edits via row
 *    re-create through Delete+Add."
 *
 * The UI-SPEC specifies inline PATCH on toggle; plan 10-10 explicitly defers.
 * Tooltip / aria-label communicate the disabled state to SR users.
 */

import { Trash2 } from "lucide-react";

import type { ScopeRowResponse } from "../../lib/api";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";

export function ScopeRowTable({
  rows,
  scopeType,
  onDelete,
}: {
  rows: ScopeRowResponse[];
  scopeType: string;
  /** Delete handler — parent runs native window.confirm + PATCH. */
  onDelete: (row: ScopeRowResponse) => Promise<void> | void;
}) {
  // IP ranges and cert hashes render monospace per UI-SPEC §Typography §Mono.
  const isMono = scopeType === "ip_range" || scopeType === "certificate";

  return (
    <table className="w-full border-collapse">
      <thead>
        <tr className="text-left border-b border-border">
          <th className="py-2 px-3 brand-caption text-muted-foreground">
            Value
          </th>
          <th className="py-2 px-3 brand-caption text-muted-foreground">
            Contact
          </th>
          <th className="py-2 px-3 brand-caption text-muted-foreground">
            Exclude
          </th>
          <th className="py-2 px-3 brand-caption text-muted-foreground">
            Active test
          </th>
          <th className="py-2 px-3 brand-caption text-muted-foreground">
            Intel
          </th>
          <th className="py-2 px-3 brand-caption text-muted-foreground sr-only">
            Actions
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.id}
            className="border-b border-border/40 hover:bg-muted/10"
          >
            <td
              className={`py-2 px-3 ${
                isMono ? "brand-mono break-all" : "text-foreground"
              }`}
            >
              {row.value}
            </td>
            <td className="py-2 px-3 text-muted-foreground">
              {row.contact || "—"}
            </td>
            <td className="py-2 px-3">
              <Switch
                checked={row.exclude}
                disabled
                aria-label="Exclude flag (read-only in Phase 10 — delete and re-add to change)"
              />
            </td>
            <td className="py-2 px-3">
              <Switch
                checked={row.active_test_scope}
                disabled
                aria-label="Active-test-scope flag (read-only)"
              />
            </td>
            <td className="py-2 px-3">
              <Switch
                checked={row.intel_scope}
                disabled
                aria-label="Intel-scope flag (read-only)"
              />
            </td>
            <td className="py-2 px-3 text-right">
              <Button
                size="icon"
                variant="ghost"
                onClick={() => onDelete(row)}
                aria-label={`Delete scope row ${row.value}`}
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
