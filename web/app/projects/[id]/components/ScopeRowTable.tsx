"use client";

/**
 * ScopeRowTable — Phase 10 Plan 10-10 with inline-PATCH toggle edit (post-ship fix).
 *
 * Per-scope-type row listing. Columns:
 *   - Value (monospace for ip_range / certificate, default text otherwise)
 *   - Contact (optional contact string or em-dash)
 *   - Exclude   (Switch — inline PATCH on change)
 *   - Active test scope (Switch — inline PATCH on change)
 *   - Intel scope (Switch — inline PATCH on change)
 *   - Actions (Delete icon button — native window.confirm per UI-SPEC §ScopeRowTable)
 *
 * Parent supplies onToggle(row, patch) which PATCHes /api/projects/{id}/scope/{row_id}
 * and reloads. Parent enforces the "at least one of active_test/intel" invariant
 * (backend CHECK project_scope_rows_at_least_one_flag rejects with 422).
 */

import { Trash2 } from "lucide-react";

import type { ScopeRowResponse, ScopeRowUpdateBody } from "../../lib/api";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";

export function ScopeRowTable({
  rows,
  scopeType,
  onDelete,
  onToggle,
}: {
  rows: ScopeRowResponse[];
  scopeType: string;
  /** Delete handler — parent runs native window.confirm + DELETE. */
  onDelete: (row: ScopeRowResponse) => Promise<void> | void;
  /** Toggle handler — parent PATCHes and reloads. */
  onToggle: (
    row: ScopeRowResponse,
    patch: ScopeRowUpdateBody,
  ) => Promise<void> | void;
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
                onCheckedChange={(v) => onToggle(row, { exclude: v })}
                aria-label="Exclude flag"
              />
            </td>
            <td className="py-2 px-3">
              <Switch
                checked={row.active_test_scope}
                onCheckedChange={(v) =>
                  onToggle(row, { active_test_scope: v })
                }
                aria-label="Active-test-scope flag"
              />
            </td>
            <td className="py-2 px-3">
              <Switch
                checked={row.intel_scope}
                onCheckedChange={(v) => onToggle(row, { intel_scope: v })}
                aria-label="Intel-scope flag"
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
