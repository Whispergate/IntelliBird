"use client";

/**
 * ScenarioCard — summary card for a scenario in ScenariosSection (Surface 3e).
 * Phase 18 plan 18-07. UI-SPEC §3e verbatim.
 *
 * Renders: actor name + technique ID, completeness badge, selection checkbox,
 * Edit button (opens ScenarioStepperSheet), "Draft narrative with AI" (mounts AIScenarioNarrative).
 * Card border: complete+selected → brand-signal; else default.
 * readOnly: hides Edit + Draft narrative; checkbox disabled.
 */

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { AIScenarioNarrative } from "./AIScenarioNarrative";
import { ScenarioStepperSheet } from "./ScenarioStepperSheet";
import { patchScenario, type ActorProfile, type TiberScenario } from "../lib/api";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ScenarioCardProps {
  scenario: TiberScenario;
  actors: ActorProfile[];
  projectId: string;
  reportId: string;
  cbestMode: boolean;
  readOnly: boolean;
  totalSelected: number;
  onScenarioUpdate: (updated: TiberScenario) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ScenarioCard({
  scenario,
  actors,
  projectId,
  reportId,
  cbestMode,
  readOnly,
  totalSelected,
  onScenarioUpdate,
}: ScenarioCardProps) {
  const [stepperOpen, setStepperOpen] = useState(false);
  const [narrativeOpen, setNarrativeOpen] = useState(false);

  const isSelected = scenario.selected_for_inclusion;
  const atSelectionCap = totalSelected >= 6 && !isSelected;

  // Compute missing fields
  function getMissingFields(): string[] {
    const missing: string[] = [];
    if (!scenario.actor_id) missing.push("actor");
    if (!scenario.cif_or_cbs_label) missing.push(cbestMode ? "CBS" : "CIF");
    if (!scenario.objective_type) missing.push("objective");
    if (!scenario.attack_technique_id) missing.push("technique");
    if (!scenario.procedure_text) missing.push("procedure");
    return missing;
  }

  const missingFields = getMissingFields();
  const isIncomplete = missingFields.length > 0;
  const isComplete = missingFields.length === 0;

  function getActorName(): string {
    if (!scenario.actor_id) return "—";
    return actors.find((a) => a.id === scenario.actor_id)?.name ?? scenario.actor_id.slice(0, 8);
  }

  async function onToggleSelection(checked: boolean) {
    try {
      const updated = await patchScenario({
        projectId,
        reportId,
        scenarioId: scenario.id,
        body: { selected_for_inclusion: checked },
      });
      onScenarioUpdate(updated);
    } catch (e) {
      toast.error(
        `Could not update scenario. ${e instanceof Error ? e.message : String(e)}`,
      );
    }
  }

  return (
    <>
      <Card
        className={[
          isSelected && isComplete
            ? "border-2 border-[var(--brand-signal)]"
            : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              {/* Selection checkbox */}
              {!readOnly && (
                <TooltipProvider delayDuration={300}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span>
                        <Checkbox
                          id={`select-${scenario.id}`}
                          checked={isSelected}
                          onCheckedChange={(checked) => onToggleSelection(checked === true)}
                          disabled={atSelectionCap}
                        />
                      </span>
                    </TooltipTrigger>
                    {atSelectionCap && (
                      <TooltipContent side="right" className="text-xs max-w-64">
                        Maximum 6 scenarios selected. Deselect one to select another.
                      </TooltipContent>
                    )}
                  </Tooltip>
                </TooltipProvider>
              )}

              <div className="min-w-0">
                <p className="text-sm font-medium truncate">
                  {scenario.cif_or_cbs_label
                    ? `${cbestMode ? "CBS" : "CIF"}: ${scenario.cif_or_cbs_label}`
                    : `Scenario ${scenario.sort_order + 1}`}
                </p>
                <p className="text-xs text-muted-foreground">
                  Actor: {getActorName()}
                  {scenario.attack_technique_id && ` · ${scenario.attack_technique_id}`}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-1 shrink-0">
              {!readOnly && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setStepperOpen(true)}
                >
                  Edit
                </Button>
              )}
            </div>
          </div>
        </CardHeader>

        <CardContent className="pt-0 space-y-2">
          {/* Incompleteness badge */}
          {isIncomplete && (
            <Badge
              variant="outline"
              className="text-orange-300 border-orange-600 brand-caption"
            >
              incomplete: {missingFields.join(", ")}
            </Badge>
          )}

          {/* AI narrative button / inline component */}
          {!readOnly && (
            <>
              {!narrativeOpen ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full"
                  onClick={() => setNarrativeOpen(true)}
                >
                  <Sparkles size={14} className="mr-1" />
                  {scenario.ai_draft_narrative ? "Re-draft with AI" : "Draft narrative with AI"}
                </Button>
              ) : (
                <AIScenarioNarrative
                  projectId={projectId}
                  reportId={reportId}
                  scenarioId={scenario.id}
                  initialNarrative={scenario.ai_draft_narrative}
                  initialMetadata={scenario.ai_draft_metadata}
                  readOnly={readOnly}
                  onNarrativeUpdate={(narrative, metadata) => {
                    onScenarioUpdate({
                      ...scenario,
                      ai_draft_narrative: narrative,
                      ai_draft_metadata: metadata,
                    });
                  }}
                />
              )}
            </>
          )}

          {/* Read-only: show narrative if present */}
          {readOnly && scenario.ai_draft_narrative && (
            <AIScenarioNarrative
              projectId={projectId}
              reportId={reportId}
              scenarioId={scenario.id}
              initialNarrative={scenario.ai_draft_narrative}
              initialMetadata={scenario.ai_draft_metadata}
              readOnly
            />
          )}

          {/* Objective + procedure preview */}
          {scenario.objective_type && (
            <p className="text-xs text-muted-foreground">
              <span className="font-medium">Objective:</span> {scenario.objective_type}
            </p>
          )}
          {scenario.procedure_text && (
            <p className="text-xs text-muted-foreground line-clamp-2">
              {scenario.procedure_text}
            </p>
          )}

          {/* Selection label for read-only */}
          {readOnly && (
            <Label className="text-xs text-muted-foreground">
              {isSelected ? "Selected for inclusion" : "Not selected"}
            </Label>
          )}
        </CardContent>
      </Card>

      {/* Scenario stepper sheet */}
      {!readOnly && (
        <ScenarioStepperSheet
          open={stepperOpen}
          onClose={() => setStepperOpen(false)}
          projectId={projectId}
          reportId={reportId}
          scenario={scenario}
          actors={actors}
          cbestMode={cbestMode}
          onScenarioUpdate={(updated) => {
            onScenarioUpdate(updated);
          }}
        />
      )}
    </>
  );
}
