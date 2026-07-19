"use client";

/**
 * ScenarioStepperSheet - Surface 4: 5-step scenario builder Sheet.
 * UI-SPEC §Surface 4 verbatim.
 *
 * Steps: Actor → CIF/CBS → Objective → Technique → Procedure
 * Auto-save per step (silent). Toast only on final "Save scenario".
 * Close stepper: closes without saving current incomplete step.
 */

import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, ChevronRight, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { patchScenario, type ActorProfile, type ObjectiveType, type TiberScenario } from "../lib/api";

// ---------------------------------------------------------------------------
// TECH_CHIP_STYLE from EventDetailDrawer.tsx - verbatim
// ---------------------------------------------------------------------------

const TECH_CHIP_STYLE = {
  backgroundColor: "rgba(159, 225, 203, 0.12)",
  color: "#9FE1CB",
  borderColor: "#0F6E56",
};

// ---------------------------------------------------------------------------
// Attack technique search types
// ---------------------------------------------------------------------------

interface AttackTechnique {
  technique_id: string;
  name: string;
}

// ---------------------------------------------------------------------------
// Step definitions
// ---------------------------------------------------------------------------

interface StepDef {
  id: string;
  label: string;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ScenarioStepperSheetProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  reportId: string;
  scenario: TiberScenario;
  actors: ActorProfile[];
  cbestMode: boolean;
  onScenarioUpdate: (updated: TiberScenario) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ScenarioStepperSheet({
  open,
  onClose,
  projectId,
  reportId,
  scenario,
  actors,
  cbestMode,
  onScenarioUpdate,
}: ScenarioStepperSheetProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [saving, setSaving] = useState(false);

  // Local draft state - step fields
  const [selectedActorId, setSelectedActorId] = useState<string>(scenario.actor_id ?? "");
  const [cifCbsLabel, setCifCbsLabel] = useState<string>(scenario.cif_or_cbs_label ?? "");
  const [objectiveType, setObjectiveType] = useState<ObjectiveType | "">(
    scenario.objective_type ?? "",
  );
  const [techniqueId, setTechniqueId] = useState<string>(scenario.attack_technique_id ?? "");
  const [techniqueQuery, setTechniqueQuery] = useState<string>(scenario.attack_technique_id ?? "");
  const [techniqueResults, setTechniqueResults] = useState<AttackTechnique[]>([]);
  const [techniqueLoading, setTechniqueLoading] = useState(false);
  const [procedureText, setProcedureText] = useState<string>(scenario.procedure_text ?? "");

  const techniqueDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset to initial state when scenario changes
  useEffect(() => {
    setCurrentStep(0);
    setSelectedActorId(scenario.actor_id ?? "");
    setCifCbsLabel(scenario.cif_or_cbs_label ?? "");
    setObjectiveType(scenario.objective_type ?? "");
    setTechniqueId(scenario.attack_technique_id ?? "");
    setTechniqueQuery(scenario.attack_technique_id ?? "");
    setProcedureText(scenario.procedure_text ?? "");
  }, [scenario.id]);

  const steps: StepDef[] = [
    { id: "actor", label: "Actor" },
    { id: "cif_cbs", label: cbestMode ? "CBS" : "CIF / CBS" },
    { id: "objective", label: "Objective" },
    { id: "technique", label: "Technique" },
    { id: "procedure", label: "Procedure" },
  ];

  // Current step required-field check
  function isCurrentStepFilled(): boolean {
    switch (currentStep) {
      case 0:
        return selectedActorId.length > 0;
      case 1:
        return cifCbsLabel.trim().length > 0;
      case 2:
        return objectiveType.length > 0;
      case 3:
        return techniqueId.length > 0;
      case 4:
        return procedureText.trim().length > 0;
      default:
        return false;
    }
  }

  // Build step-specific patch body
  function getStepPatchBody(): Record<string, unknown> {
    switch (currentStep) {
      case 0:
        return { actor_id: selectedActorId };
      case 1:
        return { cif_or_cbs_label: cifCbsLabel };
      case 2:
        return { objective_type: objectiveType };
      case 3:
        return { attack_technique_id: techniqueId };
      case 4:
        return { procedure_text: procedureText };
      default:
        return {};
    }
  }

  async function handleNext() {
    if (!isCurrentStepFilled()) return;
    setSaving(true);
    try {
      const updated = await patchScenario({
        projectId,
        reportId,
        scenarioId: scenario.id,
        body: getStepPatchBody() as Parameters<typeof patchScenario>[0]["body"],
      });
      onScenarioUpdate(updated);

      if (currentStep === 4) {
        // Final step
        toast.success("Scenario saved.");
        onClose();
      } else {
        setCurrentStep((s) => s + 1);
        // Silent on intermediate steps
      }
    } catch (e) {
      const detail = e instanceof Error ? e.message : String(e);
      toast.error(`Could not save step. ${detail}`);
    } finally {
      setSaving(false);
    }
  }

  // Technique search - debounced
  useEffect(() => {
    if (currentStep !== 3) return;
    if (techniqueDebounce.current) clearTimeout(techniqueDebounce.current);
    techniqueDebounce.current = setTimeout(async () => {
      if (!techniqueQuery.trim()) {
        setTechniqueResults([]);
        return;
      }
      setTechniqueLoading(true);
      try {
        const res = await fetch(
          `/api/attack-techniques?q=${encodeURIComponent(techniqueQuery)}&limit=20`,
        );
        if (res.ok) {
          const data: AttackTechnique[] = await res.json();
          setTechniqueResults(data);
        }
      } catch {
        // Non-fatal
      } finally {
        setTechniqueLoading(false);
      }
    }, 300);
    return () => {
      if (techniqueDebounce.current) clearTimeout(techniqueDebounce.current);
    };
  }, [techniqueQuery, currentStep]);

  // ---------------------------------------------------------------------------
  // Step content
  // ---------------------------------------------------------------------------

  function renderStepContent() {
    switch (currentStep) {
      case 0:
        return (
          <div className="space-y-2">
            <Label htmlFor="actor-select">Select threat actor</Label>
            <Select value={selectedActorId} onValueChange={setSelectedActorId}>
              <SelectTrigger id="actor-select">
                <SelectValue placeholder="Choose an actor from the Actor Profiles section" />
              </SelectTrigger>
              <SelectContent>
                {actors.length === 0 ? (
                  <SelectItem value="__none" disabled>
                    No actor profiles available - add actors first
                  </SelectItem>
                ) : (
                  actors.map((actor) => (
                    <SelectItem key={actor.id} value={actor.id}>
                      {actor.name}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
          </div>
        );

      case 1:
        return (
          <div className="space-y-2">
            <Label htmlFor="cif-cbs-input">
              {cbestMode
                ? "Critical Business Service (CBS)"
                : "Critical Infrastructure Function (CIF)"}
            </Label>
            <Input
              id="cif-cbs-input"
              value={cifCbsLabel}
              onChange={(e) => setCifCbsLabel(e.target.value)}
              placeholder={
                cbestMode ? "e.g. Core banking settlement" : "e.g. Payment processing pipeline"
              }
            />
          </div>
        );

      case 2:
        return (
          <div className="space-y-3">
            <Label>Scenario objective</Label>
            <RadioGroup
              value={objectiveType}
              onValueChange={(val) => setObjectiveType(val as ObjectiveType)}
              className="space-y-2"
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem value="availability" id="obj-availability" />
                <Label htmlFor="obj-availability" className="font-normal cursor-pointer">
                  Availability - disruption or denial of service
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="integrity" id="obj-integrity" />
                <Label htmlFor="obj-integrity" className="font-normal cursor-pointer">
                  Integrity - data manipulation or corruption
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="confidentiality" id="obj-confidentiality" />
                <Label htmlFor="obj-confidentiality" className="font-normal cursor-pointer">
                  Confidentiality - unauthorised data access or exfiltration
                </Label>
              </div>
            </RadioGroup>
          </div>
        );

      case 3:
        return (
          <div className="space-y-3">
            <Label htmlFor="technique-search">Search ATT&amp;CK technique</Label>
            <Input
              id="technique-search"
              value={techniqueQuery}
              onChange={(e) => setTechniqueQuery(e.target.value)}
              placeholder="Search by technique ID (T1566) or name…"
            />
            {techniqueId && (
              <p className="text-xs text-muted-foreground">
                Selected:{" "}
                <span className="font-medium" style={{ color: TECH_CHIP_STYLE.color }}>
                  {techniqueId}
                </span>
              </p>
            )}
            <div className="max-h-[240px] overflow-y-auto space-y-1.5 rounded-md border border-border p-2">
              {techniqueLoading && (
                <p className="text-xs text-muted-foreground flex items-center gap-1">
                  <Loader2 size={12} className="animate-spin" />
                  Searching…
                </p>
              )}
              {!techniqueLoading && techniqueResults.length === 0 && techniqueQuery.trim() && (
                <p className="text-xs text-muted-foreground">
                  No techniques match &lsquo;{techniqueQuery}&rsquo;. Try a different ID or keyword.
                </p>
              )}
              {!techniqueLoading && techniqueResults.length === 0 && !techniqueQuery.trim() && (
                <p className="text-xs text-muted-foreground">
                  Start typing to search ATT&amp;CK techniques.
                </p>
              )}
              {techniqueResults.map((tech) => {
                const isSelected = techniqueId === tech.technique_id;
                return (
                  <button
                    key={tech.technique_id}
                    type="button"
                    className="w-full text-left"
                    onClick={() => setTechniqueId(tech.technique_id)}
                  >
                    <span
                      className="inline-flex items-center gap-1 rounded border px-2 py-1 brand-caption cursor-pointer hover:opacity-80 transition-opacity"
                      style={TECH_CHIP_STYLE}
                    >
                      {tech.technique_id} - {tech.name}
                      {isSelected && (
                        <CheckCircle2 size={10} className="ml-1 text-green-400 shrink-0" />
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        );

      case 4:
        return (
          <div className="space-y-2">
            <Label htmlFor="procedure-text">Procedure description</Label>
            <Textarea
              id="procedure-text"
              rows={6}
              value={procedureText}
              onChange={(e) => setProcedureText(e.target.value)}
              placeholder="Describe the specific procedure the actor would use to execute this technique against the target CIF/CBS."
            />
          </div>
        );

      default:
        return null;
    }
  }

  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <SheetContent side="right" className="w-[560px] max-w-[100vw] flex flex-col p-0">
        <SheetHeader className="px-6 pt-6 pb-4 border-b border-border shrink-0">
          <SheetTitle>Scenario builder</SheetTitle>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {/* Step indicator row - UI-SPEC §Surface 4 verbatim */}
          <div className="flex items-center gap-2 mb-6 overflow-x-auto">
            {steps.map((step, i) => (
              <React.Fragment key={step.id}>
                <div
                  className={cn(
                    "flex items-center gap-1.5 text-xs font-medium whitespace-nowrap px-2 py-1 rounded-md",
                    i === currentStep
                      ? "bg-[var(--brand-signal)]/20 text-[var(--brand-signal)]"
                      : i < currentStep
                        ? "text-green-300"
                        : "text-muted-foreground",
                  )}
                >
                  {i < currentStep ? (
                    <CheckCircle2 size={12} />
                  ) : (
                    <span className="w-4 h-4 rounded-full border border-current flex items-center justify-center text-[10px]">
                      {i + 1}
                    </span>
                  )}
                  {step.label}
                </div>
                {i < steps.length - 1 && (
                  <ChevronRight size={12} className="text-muted-foreground/40 shrink-0" />
                )}
              </React.Fragment>
            ))}
          </div>

          {/* Step content */}
          {renderStepContent()}
        </div>

        {/* Sticky footer */}
        <div className="sticky bottom-0 bg-card border-t border-border pt-4 pb-4 px-6 flex items-center gap-2 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setCurrentStep((s) => Math.max(0, s - 1))}
            disabled={currentStep === 0 || saving}
          >
            Back
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={handleNext}
            disabled={!isCurrentStepFilled() || saving}
          >
            {saving ? (
              <>
                <Loader2 size={14} className="animate-spin mr-1" />
                Saving…
              </>
            ) : currentStep === 4 ? (
              "Save scenario"
            ) : (
              "Next"
            )}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto mr-2"
            onClick={onClose}
            disabled={saving}
          >
            Close stepper
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
