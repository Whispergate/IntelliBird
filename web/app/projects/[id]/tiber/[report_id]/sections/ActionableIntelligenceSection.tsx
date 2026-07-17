"use client";

/**
 * ActionableIntelligenceSection — Section 3b: Actionable Intelligence Assessment.
 * UI-SPEC §3b.
 *
 * Auto-populated + manual. Refresh button opens RefreshDiffModal (wired in 18-07).
 * readOnly: fields disabled, save + refresh buttons unmounted.
 */

import { useState } from "react";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { MultiValueInput } from "../../components/MultiValueInput";
import { RefreshDiffModal } from "../RefreshDiffModal";
import { patchReport, type TiberReport } from "../../lib/api";

interface ActionableIntelligenceSectionProps {
  projectId: string;
  report: TiberReport;
  cbestMode: boolean;
  readOnly: boolean;
  onPatch: (updated: TiberReport) => void;
}

export function ActionableIntelligenceSection({
  projectId,
  report,
  readOnly,
  onPatch,
}: ActionableIntelligenceSectionProps) {
  const [summaryText, setSummaryText] = useState(report.aia_summary_text ?? "");
  const [recommendations, setRecommendations] = useState<string[]>(
    report.aia_recommendations,
  );
  const [saving, setSaving] = useState(false);
  const [refreshModalOpen, setRefreshModalOpen] = useState(false);

  async function onSave() {
    setSaving(true);
    try {
      const updated = await patchReport({
        projectId,
        reportId: report.id,
        body: {
          aia_summary_text: summaryText || null,
          aia_recommendations: recommendations,
        },
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
        <h2 className="brand-heading">Actionable Intelligence Assessment</h2>
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

      <div className="space-y-4 max-w-2xl">
        {/* Summary text */}
        <div className="space-y-1.5">
          <Label htmlFor="aia-summary">Summary text</Label>
          <Textarea
            id="aia-summary"
            rows={6}
            value={summaryText}
            onChange={(e) => setSummaryText(e.target.value)}
            disabled={readOnly}
            placeholder="Summarise the key actionable intelligence findings for this engagement period…"
          />
        </div>

        {/* Analyst recommendations */}
        <div className="space-y-1.5">
          <Label>Analyst recommendations</Label>
          <p className="text-xs text-muted-foreground">
            Specific, actionable recommendations. At least 1 required.
          </p>
          <MultiValueInput
            values={recommendations}
            onChange={setRecommendations}
            placeholder="e.g. Patch CVE-2024-1234 on internet-facing assets"
            disabled={readOnly}
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
          section="actionable_intelligence"
          onApplied={(updatedReport) => {
            onPatch(updatedReport);
            setRefreshModalOpen(false);
          }}
        />
      )}
    </div>
  );
}
