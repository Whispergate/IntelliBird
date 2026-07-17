"use client";

/**
 * ScopeSection — Section 3a: Scope of Intelligence Research.
 * UI-SPEC §3a.
 *
 * Manual entry only: engagement window dates + in/out-scope assets.
 * Save button fires PATCH on report.
 * readOnly: fields disabled, save button unmounted.
 */

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MultiValueInput } from "../../components/MultiValueInput";
import { patchReport, type TiberReport } from "../../lib/api";

interface ScopeSectionProps {
  projectId: string;
  report: TiberReport;
  cbestMode: boolean;
  readOnly: boolean;
  onPatch: (updated: TiberReport) => void;
}

export function ScopeSection({ projectId, report, readOnly, onPatch }: ScopeSectionProps) {
  const [windowStart, setWindowStart] = useState(report.engagement_window_start ?? "");
  const [windowEnd, setWindowEnd] = useState(report.engagement_window_end ?? "");
  const [inScopeAssets, setInScopeAssets] = useState<string[]>(report.in_scope_assets);
  const [outOfScopeAssets, setOutOfScopeAssets] = useState<string[]>(report.out_of_scope_assets);
  const [saving, setSaving] = useState(false);

  async function onSave() {
    setSaving(true);
    try {
      const updated = await patchReport({
        projectId,
        reportId: report.id,
        body: {
          engagement_window_start: windowStart || null,
          engagement_window_end: windowEnd || null,
          in_scope_assets: inScopeAssets,
          out_of_scope_assets: outOfScopeAssets,
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
        <h2 className="brand-heading">Scope of Intelligence Research</h2>
        <div>
          {!readOnly && (
            <Button variant="default" onClick={onSave} disabled={saving}>
              {saving ? "Saving…" : "Save section"}
            </Button>
          )}
        </div>
      </div>

      <div className="space-y-4 max-w-2xl">
        {/* Engagement window */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="engagement-start">Engagement window start</Label>
            <Input
              id="engagement-start"
              type="date"
              value={windowStart}
              onChange={(e) => setWindowStart(e.target.value)}
              disabled={readOnly}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="engagement-end">Engagement window end</Label>
            <Input
              id="engagement-end"
              type="date"
              value={windowEnd}
              onChange={(e) => setWindowEnd(e.target.value)}
              disabled={readOnly}
            />
          </div>
        </div>

        {/* In-scope assets */}
        <div className="space-y-1.5">
          <Label>In-scope assets</Label>
          <p className="text-xs text-muted-foreground">
            Systems, services, and infrastructure included in this engagement. At least 1
            required.
          </p>
          <MultiValueInput
            values={inScopeAssets}
            onChange={setInScopeAssets}
            placeholder="e.g. Core banking API"
            disabled={readOnly}
          />
        </div>

        {/* Out-of-scope assets */}
        <div className="space-y-1.5">
          <Label>Out-of-scope assets</Label>
          <p className="text-xs text-muted-foreground">
            Systems explicitly excluded from this engagement (empty array is valid).
          </p>
          <MultiValueInput
            values={outOfScopeAssets}
            onChange={setOutOfScopeAssets}
            placeholder="e.g. DR environment"
            disabled={readOnly}
          />
        </div>
      </div>
    </div>
  );
}
