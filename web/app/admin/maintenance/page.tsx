"use client";

/**
 * /admin/maintenance — Maintenance Window management page.
 * Phase 16 plan 16-07. H-7 maintenance window suppression.
 *
 * Sections:
 *   - ActiveWindowBanner (top — also shown on /admin/monitoring)
 *   - CreateWindowForm (create new maintenance window)
 *   - History list: all windows sorted desc by start_at, with Delete button
 *
 * Admin-only. Non-admin sees 403 message.
 */

import { useState, useEffect, useCallback } from "react";
import { toast } from "sonner";
import { Trash2 } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { ActiveWindowBanner } from "./components/ActiveWindowBanner";
import { CreateWindowForm } from "./components/CreateWindowForm";
import { useSession } from "next-auth/react";

type MaintenanceWindow = {
  id: string;
  start_at: string;
  end_at: string;
  reason: string | null;
  created_by_user_id: string | null;
  created_at: string;
};

function windowStatus(start: string, end: string): "Active" | "Future" | "Past" {
  const now = Date.now();
  const s = new Date(start).getTime();
  const e = new Date(end).getTime();
  if (now >= s && now <= e) return "Active";
  if (now < s) return "Future";
  return "Past";
}

const STATUS_STYLES: Record<string, React.CSSProperties> = {
  Active: {
    background: "rgba(239,159,39,0.15)",
    border: "1px solid #EF9F27",
    color: "#EF9F27",
  },
  Future: {
    background: "rgba(96,165,250,0.15)",
    border: "1px solid #60a5fa",
    color: "#60a5fa",
  },
  Past: {
    background: "rgba(136,135,128,0.10)",
    border: "1px solid #888780",
    color: "#888780",
  },
};

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function MaintenancePage() {
  const { data: session } = useSession();
  const user = (session?.user as { role?: string } | undefined) ?? null;

  const [windows, setWindows] = useState<MaintenanceWindow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchWindows = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/maintenance-window");
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
      const data: MaintenanceWindow[] = await res.json();
      setWindows(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchWindows();
  }, [fetchWindows]);

  async function handleDelete(w: MaintenanceWindow) {
    const label = w.reason
      ? `"${w.reason}"`
      : `window starting ${formatDateTime(w.start_at)}`;
    if (!window.confirm(`Delete maintenance ${label}? This cannot be undone.`)) {
      return;
    }
    setDeletingId(w.id);
    try {
      const res = await fetch(`/api/admin/maintenance-window/${w.id}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail =
          typeof body?.detail === "string" ? body.detail : res.statusText;
        toast.error(`Delete failed: ${detail}`);
        return;
      }
      toast.success("Maintenance window deleted.");
      fetchWindows();
    } catch (err) {
      toast.error(
        `Error: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setDeletingId(null);
    }
  }

  // Non-admin guard
  if (error === "forbidden" || (user && user.role !== "Admin")) {
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
    <div className="p-6 flex flex-col gap-6">
      <ActiveWindowBanner />

      <h1 className="brand-heading">Maintenance Windows</h1>

      <CreateWindowForm onSuccess={fetchWindows} />

      <div className="flex flex-col gap-3">
        <h2
          className="brand-caption text-muted-foreground text-xs uppercase tracking-wide"
        >
          Window history
        </h2>

        {loading && (
          <p className="text-sm text-muted-foreground">Loading…</p>
        )}

        {!loading && error && error !== "forbidden" && (
          <p className="text-sm" style={{ color: "#fca5a5" }}>
            {error}
          </p>
        )}

        {!loading && !error && (
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Start</TableHead>
                  <TableHead>End</TableHead>
                  <TableHead style={{ width: 90 }}>Status</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead style={{ width: 60 }} />
                </TableRow>
              </TableHeader>
              <TableBody>
                {windows.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center py-10">
                      <p className="text-sm text-muted-foreground">
                        No maintenance windows scheduled.
                      </p>
                    </TableCell>
                  </TableRow>
                )}
                {windows.map((w) => {
                  const status = windowStatus(w.start_at, w.end_at);
                  const statusStyle =
                    STATUS_STYLES[status] ?? STATUS_STYLES.Past;
                  return (
                    <TableRow key={w.id}>
                      <TableCell className="text-xs">
                        {formatDateTime(w.start_at)}
                      </TableCell>
                      <TableCell className="text-xs">
                        {formatDateTime(w.end_at)}
                      </TableCell>
                      <TableCell>
                        <span
                          className="brand-caption h-5 px-2 inline-flex items-center rounded text-xs"
                          style={statusStyle}
                        >
                          {status}
                        </span>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {w.reason ?? "—"}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label="Delete window"
                          disabled={deletingId === w.id}
                          onClick={() => handleDelete(w)}
                          style={{ color: "hsl(var(--destructive))" }}
                        >
                          <Trash2 size={15} />
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </Card>
        )}
      </div>
    </div>
  );
}
