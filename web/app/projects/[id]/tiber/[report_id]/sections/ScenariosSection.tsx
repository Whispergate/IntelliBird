"use client";

/**
 * ScenariosSection — Section 3e: Threat Scenarios.
 * /07. UI-SPEC §3e.
 *
 * Auto-populated + manual. Scenario selection indicator + ScenarioCard grid.
 * Stepper Sheet (Surface 4) wired via ScenarioCard.
 * AI narrative streaming (Surface 6) wired via ScenarioCard.
 * Refresh diff modal (Surface 5) wired via RefreshDiffModal.
 * readOnly: no add/edit/select actions.
 */

import { useState } from "react";
import { toast } from "sonner";
import { Plus, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScenarioCard } from "../ScenarioCard";
import { RefreshDiffModal } from "../RefreshDiffModal";
import {
  createScenario,
  type ActorProfile,
  type TiberReport,
  type TiberScenario,
} from "../../lib/api";

interface ScenariosSectionProps {
  projectId: string;
  report: TiberReport;
  cbestMode: boolean;
  readOnly: boolean;
  scenarios: TiberScenario[];
  actors: ActorProfile[];
  onScenariosChange: (scenarios: TiberScenario[]) => void;
  onReportUpdate?: (updated: TiberReport) => void;
}

export function ScenariosSection({
  projectId,
  report,
  cbestMode,
  readOnly,
  scenarios,
  actors,
  onScenariosChange,
  onReportUpdate,
}: ScenariosSectionProps) {
  const [adding, setAdding] = useState(false);
  const [refreshModalOpen, setRefreshModalOpen] = useState(false);

  const selectedScenarios = scenarios.filter((s) => s.selected_for_inclusion);
  const selectedCount = selectedScenarios.length;
  const totalCount = scenarios.length;
  const atCap = totalCount >= 6;

  async function onAddScenario() {
    if (atCap) return;
    setAdding(true);
    try {
      const scenario = await createScenario({
        projectId,
        reportId: report.id,
      });
      // Add to list — stepper opens via ScenarioCard immediately
      onScenariosChange([...scenarios, scenario]);
    } catch (e) {
      toast.error(
        `Could not create scenario. ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setAdding(false);
    }
  }

  function handleScenarioUpdate(updated: TiberScenario) {
    onScenariosChange(scenarios.map((s) => (s.id === updated.id ? updated : s)));
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="brand-heading">Threat Scenarios</h2>
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
            <Button
              variant="outline"
              size="sm"
              onClick={onAddScenario}
              disabled={atCap || adding}
            >
              <Plus size={14} className="mr-1" />
              Add scenario
            </Button>
          )}
        </div>
      </div>

      {/* Selection indicator */}
      <div className="flex items-center gap-2 mb-4">
        <span className="text-sm text-muted-foreground">
          {selectedCount} of {totalCount} selected
        </span>
        <Badge
          variant="outline"
          className={
            selectedCount >= 3
              ? "text-green-300 border-green-700"
              : "text-red-300 border-red-600"
          }
        >
          {selectedCount >= 3
            ? "≥3 required — met"
            : `${3 - selectedCount} more required`}
        </Badge>
      </div>

      {/* Scenario cards */}
      {scenarios.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No scenarios yet. Use &ldquo;Refresh from project data&rdquo; or add manually.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 max-w-2xl">
          {scenarios.map((scenario) => (
            <ScenarioCard
              key={scenario.id}
              scenario={scenario}
              actors={actors}
              projectId={projectId}
              reportId={report.id}
              cbestMode={cbestMode}
              readOnly={readOnly}
              totalSelected={selectedCount}
              onScenarioUpdate={handleScenarioUpdate}
            />
          ))}
        </div>
      )}

      {/* Refresh diff modal — Surface 5 */}
      {!readOnly && (
        <RefreshDiffModal
          open={refreshModalOpen}
          onOpenChange={setRefreshModalOpen}
          projectId={projectId}
          reportId={report.id}
          section="scenarios"
          onApplied={(updatedReport) => {
            onReportUpdate?.(updatedReport);
            setRefreshModalOpen(false);
          }}
        />
      )}
    </div>
  );
}
