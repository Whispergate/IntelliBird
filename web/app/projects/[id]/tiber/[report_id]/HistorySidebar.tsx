"use client";

/**
 * HistorySidebar — Surface 8: right 280px export history timeline.
 * UI-SPEC §Surface 8 verbatim.
 *
 * Reverse-chronological export history list with FormatBadge + version + download.
 * Format filter <Select> synced to ?history_format= URL param.
 * Download links use relative URL traversing /api proxy (CLAUDE.md browser fetch convention).
 */

import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { FormatBadge } from "../components/FormatBadge";
import { listExports, type ExportRead, type ReportFormat } from "../lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format absolute date as "YYYY-MM-DD HH:mm" — UI-SPEC §Surface 8 verbatim */
function formatAbsoluteDate(iso: string): string {
  try {
    const d = new Date(iso);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    const hh = String(d.getHours()).padStart(2, "0");
    const min = String(d.getMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type HistoryFormatFilter = "all" | ReportFormat;

interface HistorySidebarProps {
  projectId: string;
  reportId: string;
  /** When true, trigger a refresh of the export list (new export queued). */
  refreshTrigger?: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function HistorySidebar({ projectId, reportId, refreshTrigger }: HistorySidebarProps) {
  const [exports, setExports] = useState<ExportRead[]>([]);
  const [formatFilter, setFormatFilter] = useState<HistoryFormatFilter>("all");

  // Load exports on mount + when refreshTrigger changes
  useEffect(() => {
    listExports({
      projectId,
      reportId,
      format: formatFilter === "all" ? undefined : formatFilter,
    })
      .then((data) => {
        // Reverse-chronological sort
        const sorted = [...data].sort(
          (a, b) => new Date(b.generated_at).getTime() - new Date(a.generated_at).getTime(),
        );
        setExports(sorted);
      })
      .catch(() => {
        // Non-fatal — sidebar just stays empty
      });
  }, [projectId, reportId, formatFilter, refreshTrigger]);

  return (
    <aside className="w-[280px] border-l border-border bg-card flex flex-col overflow-hidden shrink-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <h3 className="brand-caption text-muted-foreground uppercase">Export history</h3>
        <Select
          value={formatFilter}
          onValueChange={(val) => setFormatFilter(val as HistoryFormatFilter)}
        >
          <SelectTrigger className="h-6 text-xs w-[110px] border-border">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All formats</SelectItem>
            <SelectItem value="markdown">Markdown</SelectItem>
            <SelectItem value="pdf">PDF</SelectItem>
            <SelectItem value="stix">STIX</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* History list */}
      <div className="flex-1 overflow-y-auto">
        {exports.length === 0 ? (
          <p className="text-xs text-muted-foreground px-4 py-6 text-center">
            No exports yet for this report.
          </p>
        ) : (
          exports.map((exp) => (
            <div
              key={exp.id}
              className="flex items-start justify-between px-4 py-3 border-b border-border hover:bg-background/40 transition-colors"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <FormatBadge format={exp.format} />
                  <span className="text-xs text-muted-foreground">v{exp.version_number}</span>
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {formatAbsoluteDate(exp.generated_at)}
                  {exp.generated_by_user_id && ` by ${exp.generated_by_user_id.slice(0, 8)}`}
                </p>
                <p className="text-xs text-muted-foreground/60 brand-mono truncate">
                  {exp.filename}
                </p>
              </div>
              {/* Download link — relative URL traverses proxy per CLAUDE.md convention */}
              <a
                href={`/api/projects/${projectId}/tiber/reports/${reportId}/exports/${exp.id}/download`}
                download={exp.filename}
                className="ml-2 shrink-0"
              >
                <Button variant="ghost" size="icon" aria-label="Download this export">
                  <Download size={14} />
                </Button>
              </a>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
