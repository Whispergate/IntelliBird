"use client";

/**
 * TIBERReportEditor — Surface 2 three-column report editor shell.
 * UI-SPEC §Surface 2.
 *
 * Layout:
 *   [Left 240px section sidebar] | [flex-1 main section editor] | [Right 280px history placeholder]
 *
 * Owns:
 *   - CBEST toggle state (fires PATCH immediately, toasts)
 *   - Active section navigation
 *   - Per-section completeness computation
 *   - Publish button (disabled when sections incomplete) + PublishModal
 *   - Clone-to-new-draft for published reports
 *   - Read-only enforcement (published state → readOnly prop to all sections)
 */

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { SectionSidebar, type SectionKey } from "./SectionSidebar";
import { PublishModal } from "./PublishModal";
import { ExportPanel } from "./ExportPanel";
import { HistorySidebar } from "./HistorySidebar";
import { ReportStateBadge } from "../components/ReportStateBadge";
import type { CompletionState } from "../components/CompletionBadge";
import { ScopeSection } from "./sections/ScopeSection";
import { ActionableIntelligenceSection } from "./sections/ActionableIntelligenceSection";
import { ThreatLandscapeSection } from "./sections/ThreatLandscapeSection";
import { ActorProfilesSection } from "./sections/ActorProfilesSection";
import { ScenariosSection } from "./sections/ScenariosSection";
import { ScenarioXSection } from "./sections/ScenarioXSection";
import { cloneReport, patchReport, type ActorProfile, type TiberReport, type TiberScenario } from "../lib/api";

// ---------------------------------------------------------------------------
// Completeness computation
// ---------------------------------------------------------------------------

function computeCompletionState(
  report: TiberReport,
  actors: ActorProfile[],
  scenarios: TiberScenario[],
): {
  states: Record<SectionKey, CompletionState>;
  missing: Record<SectionKey, string[]>;
} {
  const scopeMissing: string[] = [];
  if (!report.engagement_window_start) scopeMissing.push("engagement window start");
  if (!report.engagement_window_end) scopeMissing.push("engagement window end");
  if (report.in_scope_assets.length === 0) scopeMissing.push("in-scope assets (≥1)");

  const aiaMissing: string[] = [];
  if (!report.aia_summary_text) aiaMissing.push("summary text");
  if (report.aia_recommendations.length === 0) aiaMissing.push("analyst recommendations (≥1)");

  const tlMissing: string[] = [];
  if (report.tl_top_events.length < 5) tlMissing.push("top events (≥5)");
  if (!report.tl_analyst_narrative) tlMissing.push("analyst narrative");

  const actorsMissing: string[] = [];
  if (actors.length < 3) actorsMissing.push(`actor profiles (${actors.length}/3 required)`);
  const incompleteActors = actors.filter(
    (a) => !a.name || !a.motivation || !a.capability_assessment || !a.relevance_to_target,
  );
  if (incompleteActors.length > 0)
    actorsMissing.push(`${incompleteActors.length} incomplete actor profile(s)`);

  const scenariosMissing: string[] = [];
  const selectedComplete = scenarios.filter(
    (s) =>
      s.selected_for_inclusion &&
      s.actor_id &&
      s.cif_or_cbs_label &&
      s.objective_type &&
      s.attack_technique_id &&
      s.procedure_text,
  );
  if (selectedComplete.length < 3)
    scenariosMissing.push(`complete selected scenarios (${selectedComplete.length}/3 required)`);

  const scenXMissing: string[] = [];
  if (!report.scenario_x_narrative) scenXMissing.push("narrative text");

  function state(missing: string[]): CompletionState {
    if (missing.length === 0) return "complete";
    return "incomplete";
  }

  // Determine if a section has never been touched (not-started)
  const scopeNotStarted =
    !report.engagement_window_start &&
    !report.engagement_window_end &&
    report.in_scope_assets.length === 0 &&
    report.out_of_scope_assets.length === 0;
  const aiaNotStarted =
    !report.aia_summary_text && report.aia_recommendations.length === 0;
  const tlNotStarted =
    report.tl_top_events.length === 0 && !report.tl_analyst_narrative;
  const actorsNotStarted = actors.length === 0;
  const scenariosNotStarted = scenarios.length === 0;
  const scenXNotStarted = !report.scenario_x_narrative;

  return {
    states: {
      scope: scopeNotStarted ? "not-started" : state(scopeMissing),
      actionable_intelligence: aiaNotStarted ? "not-started" : state(aiaMissing),
      threat_landscape: tlNotStarted ? "not-started" : state(tlMissing),
      actor_profiles: actorsNotStarted ? "not-started" : state(actorsMissing),
      threat_scenarios: scenariosNotStarted ? "not-started" : state(scenariosMissing),
      scenario_x: scenXNotStarted ? "not-started" : state(scenXMissing),
    },
    missing: {
      scope: scopeMissing,
      actionable_intelligence: aiaMissing,
      threat_landscape: tlMissing,
      actor_profiles: actorsMissing,
      threat_scenarios: scenariosMissing,
      scenario_x: scenXMissing,
    },
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface TIBERReportEditorProps {
  projectId: string;
  report: TiberReport;
  initialActors: ActorProfile[];
  initialScenarios: TiberScenario[];
}

export function TIBERReportEditor({
  projectId,
  report: initialReport,
  initialActors,
  initialScenarios,
}: TIBERReportEditorProps) {
  const router = useRouter();
  const [report, setReport] = useState<TiberReport>(initialReport);
  const [actors, setActors] = useState<ActorProfile[]>(initialActors);
  const [scenarios, setScenarios] = useState<TiberScenario[]>(initialScenarios);
  const [activeSection, setActiveSection] = useState<SectionKey>("scope");
  const [publishModalOpen, setPublishModalOpen] = useState(false);
  const [cloning, setCloning] = useState(false);
  const [exportRefreshTrigger, setExportRefreshTrigger] = useState(0);

  const isPublished = report.state === "published";
  const isArchived = report.state === "archived";
  const readOnly = isPublished || isArchived;

  const { states: completionStates, missing: missingFields } = computeCompletionState(
    report,
    actors,
    scenarios,
  );

  const allComplete = Object.values(completionStates).every((s) => s === "complete");
  const incompleteSections = Object.entries(completionStates)
    .filter(([, s]) => s !== "complete")
    .map(([key]) => key.replace(/_/g, " "));

  // ExportPanel gate data
  const selectedCompleteScenarios = scenarios.filter(
    (s) =>
      s.selected_for_inclusion &&
      s.actor_id &&
      s.cif_or_cbs_label &&
      s.objective_type &&
      s.attack_technique_id &&
      s.procedure_text,
  );
  const selectedScenarioCount = selectedCompleteScenarios.length;
  // Completeness gaps for ExportPanel tooltip — all incomplete section names
  const exportCompletenessGaps: string[] = Object.entries(completionStates)
    .filter(([, s]) => s !== "complete")
    .flatMap(([key]) => missingFields[key as SectionKey]);

  async function onCbestToggle(checked: boolean) {
    try {
      const updated = await patchReport({
        projectId,
        reportId: report.id,
        body: { cbest_mode: checked },
      });
      setReport(updated);
      toast.success(checked ? "CBEST mode enabled." : "CBEST mode disabled.");
    } catch (e) {
      toast.error(
        `Could not update CBEST mode. ${e instanceof Error ? e.message : String(e)}`,
      );
    }
  }

  async function onClone() {
    setCloning(true);
    try {
      const cloned = await cloneReport({ projectId, reportId: report.id });
      toast.success("Cloned to new draft.");
      router.push(`/projects/${projectId}/tiber/${cloned.id}`);
    } catch (e) {
      toast.error(`Could not clone. ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCloning(false);
    }
  }

  const onReportPatch = useCallback((updated: TiberReport) => {
    setReport(updated);
  }, []);

  return (
    <div className="flex h-[calc(100vh-var(--header-height,56px))] overflow-hidden">
      {/* Left section sidebar */}
      <SectionSidebar
        activeSection={activeSection}
        onSectionChange={setActiveSection}
        completionStates={completionStates}
        missingFields={missingFields}
      />

      {/* Main column */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Report editor header */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-border bg-background shrink-0 gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <h1 className="brand-heading truncate max-w-sm">{report.title}</h1>
            <ReportStateBadge state={report.state} />
            {isPublished && (
              <Badge variant="outline" className="text-muted-foreground brand-caption shrink-0">
                Published — read only
              </Badge>
            )}
          </div>

          <div className="flex items-center gap-4 shrink-0">
            {/* CBEST toggle */}
            <div className="flex items-center gap-2">
              <Switch
                id="cbest-mode"
                checked={report.cbest_mode}
                onCheckedChange={onCbestToggle}
                disabled={readOnly}
              />
              <Label htmlFor="cbest-mode" className="text-sm cursor-pointer">
                CBEST mode
              </Label>
            </div>

            {/* Published: clone-to-new-draft */}
            {isPublished && (
              <Button variant="outline" size="sm" onClick={onClone} disabled={cloning}>
                {cloning ? "Cloning…" : "Clone to new draft"}
              </Button>
            )}

            {/* Draft: publish button */}
            {report.state === "draft" && (
              <TooltipProvider delayDuration={300}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span>
                      <Button
                        variant="default"
                        size="sm"
                        disabled={!allComplete}
                        onClick={() => setPublishModalOpen(true)}
                      >
                        Publish report
                      </Button>
                    </span>
                  </TooltipTrigger>
                  {!allComplete && (
                    <TooltipContent side="bottom" className="text-xs max-w-64">
                      Complete all required sections before publishing:{" "}
                      {incompleteSections.join(", ")}
                    </TooltipContent>
                  )}
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
        </div>

        {/* Export panel — Surface 7 (sticky Card above section content) */}
        <div className="px-6 pt-4">
          <ExportPanel
            projectId={projectId}
            reportId={report.id}
            completenessGaps={exportCompletenessGaps}
            selectedScenarioCount={selectedScenarioCount}
            onExportComplete={() => setExportRefreshTrigger((n) => n + 1)}
          />
        </div>

        {/* Section editor main area */}
        <div className="flex-1 overflow-hidden">
          {activeSection === "scope" && (
            <ScopeSection
              projectId={projectId}
              report={report}
              cbestMode={report.cbest_mode}
              readOnly={readOnly}
              onPatch={onReportPatch}
            />
          )}
          {activeSection === "actionable_intelligence" && (
            <ActionableIntelligenceSection
              projectId={projectId}
              report={report}
              cbestMode={report.cbest_mode}
              readOnly={readOnly}
              onPatch={onReportPatch}
            />
          )}
          {activeSection === "threat_landscape" && (
            <ThreatLandscapeSection
              projectId={projectId}
              report={report}
              cbestMode={report.cbest_mode}
              readOnly={readOnly}
              onPatch={onReportPatch}
            />
          )}
          {activeSection === "actor_profiles" && (
            <ActorProfilesSection
              projectId={projectId}
              report={report}
              cbestMode={report.cbest_mode}
              readOnly={readOnly}
              actors={actors}
              onActorsChange={setActors}
            />
          )}
          {activeSection === "threat_scenarios" && (
            <ScenariosSection
              projectId={projectId}
              report={report}
              cbestMode={report.cbest_mode}
              readOnly={readOnly}
              scenarios={scenarios}
              actors={actors}
              onScenariosChange={setScenarios}
              onReportUpdate={onReportPatch}
            />
          )}
          {activeSection === "scenario_x" && (
            <ScenarioXSection
              projectId={projectId}
              report={report}
              cbestMode={report.cbest_mode}
              readOnly={readOnly}
              onPatch={onReportPatch}
            />
          )}
        </div>
      </div>

      {/* Right history sidebar — Surface 8 */}
      <HistorySidebar
        projectId={projectId}
        reportId={report.id}
        refreshTrigger={exportRefreshTrigger}
      />

      {/* Publish confirmation modal */}
      <PublishModal
        open={publishModalOpen}
        onOpenChange={setPublishModalOpen}
        projectId={projectId}
        reportId={report.id}
        reportTitle={report.title}
      />
    </div>
  );
}
