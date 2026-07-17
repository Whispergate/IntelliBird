"use client";

/**
 * ScenarioXSection — Section 3f: Scenario X.
 * UI-SPEC §3f.
 *
 * Manual only. Free-form analyst narrative for additional scenarios.
 * readOnly: textarea disabled, save button unmounted.
 */

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { patchReport, type TiberReport } from "../../lib/api";

interface ScenarioXSectionProps {
  projectId: string;
  report: TiberReport;
  cbestMode: boolean;
  readOnly: boolean;
  onPatch: (updated: TiberReport) => void;
}

export function ScenarioXSection({
  projectId,
  report,
  readOnly,
  onPatch,
}: ScenarioXSectionProps) {
  const [narrative, setNarrative] = useState(report.scenario_x_narrative ?? "");
  const [saving, setSaving] = useState(false);

  async function onSave() {
    setSaving(true);
    try {
      const updated = await patchReport({
        projectId,
        reportId: report.id,
        body: { scenario_x_narrative: narrative || null },
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
        <h2 className="brand-heading">Scenario X</h2>
        <div>
          {!readOnly && (
            <Button variant="default" onClick={onSave} disabled={saving}>
              {saving ? "Saving…" : "Save section"}
            </Button>
          )}
        </div>
      </div>

      <div className="space-y-4 max-w-2xl">
        <p className="text-xs text-muted-foreground">
          Free-form analyst narrative for additional scenarios, key findings, or context outside
          the structured scenario chain.
        </p>
        <div className="space-y-1.5">
          <Label htmlFor="scenario-x-narrative">Narrative</Label>
          <Textarea
            id="scenario-x-narrative"
            rows={12}
            value={narrative}
            onChange={(e) => setNarrative(e.target.value)}
            disabled={readOnly}
            placeholder="Provide additional scenario context, novel attack paths, or analyst observations that fall outside the structured scenario chains…"
          />
        </div>
      </div>
    </div>
  );
}
