"use client";

/**
 * ScopeTabContent
 *
 * Renders one of the 7 scope_type panes for /projects/[id]. Tab-key dispatch
 * maps `?tab=scope-<type>` to a (scope_type, label, addLabel) bundle.
 *
 * Layout (per UI-SPEC §/projects/[id] detail §ScopeRowTable interactions):
 *   - Header row: "<Label> scope" heading + Add button (signal amber CTA)
 *   - Body: ScopeRowTable if rows.length > 0, else empty-state per UI-SPEC
 *     §Empty states: heading "No <type> scope rows" + body
 *     "Add rows to narrow this project's intel view."
 *
 * Backend CRUD (plan 10-04):
 *   - GET  /api/projects/{id}/scope      → listScopeRows (filtered client-side)
 *   - POST /api/projects/{id}/scope      → addScopeRow (value validated 422)
 *   - DELETE /api/projects/{id}/scope/{row_id} → deleteScopeRow
 *
 * Delete flow uses native window.confirm per UI-SPEC §Destructive
 * confirmations - "Delete scope row \"<value>\"?" matches v1.5 precedent.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import type {
  ProjectResponse,
  ScopeRowCreateBody,
  ScopeRowResponse,
  ScopeRowUpdateBody,
  ScopeType,
} from "../lib/api";
import {
  addScopeRow,
  deleteScopeRow,
  listScopeRows,
  updateScopeRow,
} from "../lib/api";
import { Button } from "@/components/ui/button";
import { ScopeRowDialog } from "./components/ScopeRowDialog";
import { ScopeRowTable } from "./components/ScopeRowTable";

/**
 * Tab key → scope metadata. The 7 scope types match backend ScopeType enum.
 * Labels + add-button copy are locked by UI-SPEC §Copywriting Contract §Primary
 * CTAs: "Add keyword / service / domain / certificate / WHOIS entry / AS
 * number / IP range".
 */
const TAB_TO_SCOPE: Record<
  string,
  { type: ScopeType; label: string; addLabel: string }
> = {
  "scope-keyword": {
    type: "keyword",
    label: "Keyword",
    addLabel: "Add keyword",
  },
  "scope-service": {
    type: "service",
    label: "Service",
    addLabel: "Add service",
  },
  "scope-domain": { type: "domain", label: "Domain", addLabel: "Add domain" },
  "scope-certificate": {
    type: "certificate",
    label: "Certificate",
    addLabel: "Add certificate",
  },
  "scope-whois": {
    type: "whois",
    label: "WHOIS",
    addLabel: "Add WHOIS entry",
  },
  "scope-as_number": {
    type: "as_number",
    label: "AS number",
    addLabel: "Add AS number",
  },
  "scope-ip_range": {
    type: "ip_range",
    label: "IP range",
    addLabel: "Add IP range",
  },
};

export function ScopeTabContent({
  project,
  tabKey,
}: {
  project: ProjectResponse;
  /** One of the 7 "scope-<type>" tab keys from ProjectTabs.tsx TABS array. */
  tabKey: string;
}) {
  const cfg = TAB_TO_SCOPE[tabKey];

  // State hooks must be unconditional - declare before the early return.
  const [rows, setRows] = useState<ScopeRowResponse[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [loading, setLoading] = useState(true);

  const scopeType = cfg?.type;

  const reload = useCallback(async () => {
    if (!scopeType) return;
    setLoading(true);
    try {
      const all = await listScopeRows(project.id);
      setRows(all.filter((r) => r.scope_type === scopeType));
    } catch {
      // Silent - toast would fire on every tab switch if the network is down.
      // Add/delete handlers still toast on their own failures.
    } finally {
      setLoading(false);
    }
  }, [project.id, scopeType]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const sortedRows = useMemo(
    () =>
      [...rows].sort((a, b) =>
        a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0,
      ),
    [rows],
  );

  // Unknown tab key - defensive fallback for deep-links with a stale/bogus
  // tab param. ProjectTabs only renders the 7 known keys, but the URL is
  // user-editable.
  if (!cfg) {
    return (
      <div className="text-muted-foreground">
        Unknown scope tab: <code className="brand-mono">{tabKey}</code>.
      </div>
    );
  }

  async function handleAdd(body: ScopeRowCreateBody) {
    try {
      await addScopeRow(project.id, body);
      toast.success(`${cfg!.label} scope row added.`);
      setDialogOpen(false);
      await reload();
    } catch (err) {
      // Backend 422 `detail` carries the exact UI-SPEC error copy (byte-for-byte
      // via scope_validators.py ValueError). Display it unmodified.
      const msg = err instanceof Error ? err.message : "Unknown error.";
      toast.error(`Could not add row. ${msg}`);
    }
  }

  async function handleDelete(row: ScopeRowResponse) {
    if (!window.confirm(`Delete scope row "${row.value}"?`)) return;
    try {
      await deleteScopeRow(project.id, row.id);
      toast.success("Scope row deleted.");
      await reload();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error.";
      toast.error(`Could not delete row. ${msg}`);
    }
  }

  async function handleToggle(
    row: ScopeRowResponse,
    patch: ScopeRowUpdateBody,
  ) {
    // Pre-flight "at least one flag" invariant - matches backend CHECK
    // constraint project_scope_rows_at_least_one_flag. Blocks the PATCH when
    // the resulting row would have both active_test_scope and intel_scope
    // false, avoiding a user-visible error round-trip.
    const merged = { ...row, ...patch };
    if (!merged.active_test_scope && !merged.intel_scope) {
      toast.error("Row must target at least intel or active test.");
      return;
    }
    // Optimistic update - revert on failure via reload.
    setRows((prev) =>
      prev.map((r) => (r.id === row.id ? { ...r, ...patch } : r)),
    );
    try {
      await updateScopeRow(project.id, row.id, patch);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error.";
      toast.error(`Could not update row. ${msg}`);
      await reload();
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="brand-heading text-foreground">{cfg.label} scope</h2>
        <Button
          onClick={() => setDialogOpen(true)}
          style={{
            backgroundColor: "var(--brand-signal)",
            color: "var(--brand-ink)",
          }}
          className="font-medium hover:opacity-90"
        >
          {cfg.addLabel}
        </Button>
      </div>

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading scope rows…</p>
      ) : sortedRows.length === 0 ? (
        <div className="py-12 text-center">
          <h3 className="brand-heading text-foreground mb-2">
            No {cfg.label.toLowerCase()} scope rows
          </h3>
          <p className="text-muted-foreground mb-4">
            Add rows to narrow this project&apos;s intel view.
          </p>
          <Button
            onClick={() => setDialogOpen(true)}
            style={{
              backgroundColor: "var(--brand-signal)",
              color: "var(--brand-ink)",
            }}
            className="font-medium hover:opacity-90"
          >
            {cfg.addLabel}
          </Button>
        </div>
      ) : (
        <ScopeRowTable
          rows={sortedRows}
          scopeType={cfg.type}
          onDelete={handleDelete}
          onToggle={handleToggle}
        />
      )}

      <ScopeRowDialog
        open={dialogOpen}
        scopeType={cfg.type}
        addLabel={cfg.addLabel}
        onSubmit={handleAdd}
        onClose={() => setDialogOpen(false)}
      />
    </div>
  );
}
