"use client";

/**
 * ActiveWindowBanner — polls GET /api/admin/maintenance-window/active every 60s.
 * H-7 maintenance window suppression.
 *
 * When 200: shows yellow alert "Maintenance window active until {end_at}".
 * When 404 (no active window): renders nothing.
 *
 * Imported on both /admin/monitoring and /admin/maintenance pages.
 */

import { useEffect, useState } from "react";

type ActiveWindow = {
  id: string;
  start_at: string;
  end_at: string;
  reason: string | null;
  created_by_user_id: string | null;
  created_at: string;
};

const POLL_INTERVAL_MS = 60_000;

function formatWindowEnd(isoEnd: string): string {
  const d = new Date(isoEnd);
  if (isNaN(d.getTime())) return isoEnd;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ActiveWindowBanner() {
  const [activeWindow, setActiveWindow] = useState<ActiveWindow | null>(null);

  async function poll() {
    try {
      const res = await fetch("/api/admin/maintenance-window/active");
      if (res.ok) {
        const data: ActiveWindow = await res.json();
        setActiveWindow(data);
      } else {
        setActiveWindow(null);
      }
    } catch {
      // Network error — don't clear existing state; silently retry
    }
  }

  useEffect(() => {
    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  if (!activeWindow) return null;

  return (
    <div
      className="flex items-start gap-3 px-4 py-3 rounded border text-sm"
      style={{
        background: "rgba(239,159,39,0.12)",
        borderColor: "#EF9F27",
        color: "#EF9F27",
        borderLeft: "4px solid #EF9F27",
      }}
      role="alert"
    >
      <span className="font-semibold shrink-0">Maintenance window active</span>
      <span style={{ color: "rgba(239,159,39,0.85)" }}>
        until {formatWindowEnd(activeWindow.end_at)} — monitoring alerts suppressed
        {activeWindow.reason ? ` (${activeWindow.reason})` : ""}
      </span>
    </div>
  );
}
