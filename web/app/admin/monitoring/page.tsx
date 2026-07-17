"use client";

/**
 * /admin/monitoring — Source Health Dashboard.
 * MON-04 dashboard requirement.
 *
 * Admin-only page. SWR-style refresh every 30s (CONTEXT.md "Claude's Discretion").
 * Shows SourceHealthTable + MonitoringConfigDrawer (per-source config editor).
 * ActiveWindowBanner imported from maintenance components.
 *
 * Non-admin users: 403 message (backend also enforces via require_admin).
 */

import { useState, useEffect, useCallback } from "react";
import { SourceHealthTable } from "./components/SourceHealthTable";
import {
  MonitoringConfigDrawer,
  type MonitoringSourceRow,
} from "./components/MonitoringConfigDrawer";
import { ActiveWindowBanner } from "../maintenance/components/ActiveWindowBanner";
import { useSession } from "next-auth/react";

const REFRESH_INTERVAL_MS = 30_000;

export default function MonitoringPage() {
  const { data: session } = useSession();
  const user = (session?.user as { role?: string } | undefined) ?? null;

  const [rows, setRows] = useState<MonitoringSourceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSource, setSelectedSource] =
    useState<MonitoringSourceRow | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const fetchSources = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/monitoring/sources");
      if (res.status === 403) {
        setError("forbidden");
        setLoading(false);
        return;
      }
      if (!res.ok) {
        setError(`HTTP ${res.status} ${res.statusText}`);
        setLoading(false);
        return;
      }
      const data: MonitoringSourceRow[] = await res.json();
      setRows(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSources();
    const interval = setInterval(fetchSources, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchSources]);

  function handleRowClick(row: MonitoringSourceRow) {
    setSelectedSource(row);
    setDrawerOpen(true);
  }

  function handleSaved() {
    fetchSources();
  }

  // Non-admin guard (client side mirror — backend enforces authoritatively)
  if (user && user.role !== "Admin") {
    return (
      <div className="p-6">
        <div
          className="p-4 rounded border text-sm"
          style={{
            background: "rgba(220,38,38,0.10)",
            borderColor: "#dc2626",
            color: "#fca5a5",
          }}
        >
          403 — Admin access required.
        </div>
      </div>
    );
  }

  if (error === "forbidden") {
    return (
      <div className="p-6">
        <div
          className="p-4 rounded border text-sm"
          style={{
            background: "rgba(220,38,38,0.10)",
            borderColor: "#dc2626",
            color: "#fca5a5",
          }}
        >
          403 — Admin access required.
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 flex flex-col gap-4">
      <ActiveWindowBanner />

      <div className="flex items-center justify-between">
        <h1 className="brand-heading">Source Health</h1>
        {loading && (
          <span className="text-xs text-muted-foreground">Loading…</span>
        )}
        {!loading && error && (
          <span className="text-xs" style={{ color: "#fca5a5" }}>
            {error}
          </span>
        )}
        {!loading && !error && (
          <span className="text-xs text-muted-foreground">
            {rows.length} source{rows.length !== 1 ? "s" : ""} — refreshes every 30s
          </span>
        )}
      </div>

      <SourceHealthTable rows={rows} onRowClick={handleRowClick} />

      <MonitoringConfigDrawer
        source={selectedSource}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        onSaved={handleSaved}
      />
    </div>
  );
}
