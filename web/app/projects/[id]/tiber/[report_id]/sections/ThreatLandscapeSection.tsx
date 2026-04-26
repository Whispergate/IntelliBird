"use client";

/**
 * ThreatLandscapeSection — Section 3c: Threat Landscape.
 * Phase 18 plan 18-06. UI-SPEC §3c.
 *
 * Auto-populated + manual. Read-only top_events Table (max 20 rows) + analyst narrative.
 * readOnly: fields disabled, save + refresh buttons unmounted.
 */

import { useState } from "react";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { RefreshDiffModal } from "../RefreshDiffModal";
import { patchReport, type TiberReport } from "../../lib/api";

interface ThreatLandscapeSectionProps {
  projectId: string;
  report: TiberReport;
  cbestMode: boolean;
  readOnly: boolean;
  onPatch: (updated: TiberReport) => void;
}

type TopEvent = {
  id?: string;
  title?: string;
  score?: number;
  observed_at?: string;
};

export function ThreatLandscapeSection({
  projectId,
  report,
  readOnly,
  onPatch,
}: ThreatLandscapeSectionProps) {
  const [narrative, setNarrative] = useState(report.tl_analyst_narrative ?? "");
  const [saving, setSaving] = useState(false);
  const [refreshModalOpen, setRefreshModalOpen] = useState(false);

  const topEvents = (report.tl_top_events as TopEvent[]).slice(0, 20);
  const totalEvents = report.tl_top_events.length;

  async function onSave() {
    setSaving(true);
    try {
      const updated = await patchReport({
        projectId,
        reportId: report.id,
        body: { tl_analyst_narrative: narrative || null },
      });
      onPatch(updated);
      toast.success("Section saved.");
    } catch (e) {
      toast.error(`Could not save section. ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="brand-heading">Threat Landscape</h2>
        <div className="flex items-center gap-2">
          {!readOnly && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setRefreshModalOpen(true)}
            >
              <RefreshCw size={14} className="mr-1" />
              Refresh from project data
            </Button>
          )}
          {!readOnly && (
            <Button variant="default" onClick={onSave} disabled={saving}>
              {saving ? "Saving…" : "Save section"}
            </Button>
          )}
        </div>
      </div>

      <div className="space-y-4 max-w-3xl">
        {/* Top events table */}
        <div className="space-y-1.5">
          <Label>Top threat events</Label>
          {totalEvents > 0 ? (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Event title</TableHead>
                    <TableHead className="w-20">Score</TableHead>
                    <TableHead className="w-32">Date</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {topEvents.map((event, i) => (
                    <TableRow key={event.id ?? i}>
                      <TableCell className="text-sm">
                        {event.title ?? "—"}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {event.score != null ? event.score.toFixed(1) : "—"}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {event.observed_at
                          ? new Date(event.observed_at).toLocaleDateString()
                          : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {totalEvents > 20 && (
                <p className="text-xs text-muted-foreground mt-1">
                  Showing top 20 of {totalEvents} events
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                {totalEvents} event{totalEvents !== 1 ? "s" : ""} auto-populated from project
                scope.
              </p>
            </>
          ) : (
            <p className="text-xs text-muted-foreground py-4 text-center border border-dashed border-border rounded-md">
              No events auto-populated yet. Use &ldquo;Refresh from project data&rdquo; to populate.
            </p>
          )}
        </div>

        {/* Analyst narrative */}
        <div className="space-y-1.5">
          <Label htmlFor="tl-narrative">Analyst narrative</Label>
          <Textarea
            id="tl-narrative"
            rows={8}
            value={narrative}
            onChange={(e) => setNarrative(e.target.value)}
            disabled={readOnly}
            placeholder="Provide analyst context on the current threat landscape relevant to this engagement…"
          />
        </div>
      </div>

      {/* Refresh diff modal — Surface 5 */}
      {!readOnly && (
        <RefreshDiffModal
          open={refreshModalOpen}
          onOpenChange={setRefreshModalOpen}
          projectId={projectId}
          reportId={report.id}
          section="threat_landscape"
          onApplied={(updatedReport) => {
            onPatch(updatedReport);
            setRefreshModalOpen(false);
          }}
        />
      )}
    </div>
  );
}
