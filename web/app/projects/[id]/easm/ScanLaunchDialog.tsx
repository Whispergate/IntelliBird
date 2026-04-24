"use client";

/**
 * ScanLaunchDialog — Phase 11 plan 11-09 (UI-SPEC §Surface 4).
 *
 * Shadcn Dialog with:
 *   - Mode RadioGroup (Passive default / Active gated)
 *   - Module multi-select checklist from GET /api/easm/safelist (ScrollArea)
 *   - Shodan optional note (conditional)
 *   - Error-to-toast mapping per UI-SPEC §Copywriting Contract (byte-exact)
 *   - Authority-matrix disabled states per UI-SPEC §Authority-Matrix Visual Contract
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { EASMSafelist, ScanMode } from "./lib/api";
import { getSafelist, launchScan } from "./lib/api";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ProjectGateData {
  active_scans_authorised: boolean;
  active_auth_confirmed_at: string | null;
}

interface ScanLaunchDialogProps {
  projectId: string;
  isOpen: boolean;
  onClose: () => void;
  /** Project gate data — active_scans_authorised + active_auth_confirmed_at */
  project: ProjectGateData | null;
  /** True when the current user has Lead or global Admin authority */
  userCanLaunchActive: boolean;
  /** Called after successful scan launch so the parent can refetch */
  onLaunched?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns the disabled tooltip text for the Active radio, or null if enabled */
function activeDisabledReason(
  project: ProjectGateData | null,
  userCanLaunchActive: boolean,
): string | null {
  if (!userCanLaunchActive) {
    return "Only project Leads and global Admins may launch active scans.";
  }
  if (!project?.active_scans_authorised) {
    return "Active scans require active-scan authorisation. Set it on the Settings tab.";
  }
  return null;
}

// ---------------------------------------------------------------------------
// Module checklist item
// ---------------------------------------------------------------------------

function ModuleItem({
  name,
  checked,
  onToggle,
}: {
  name: string;
  checked: boolean;
  onToggle: (name: string) => void;
}) {
  return (
    <div className="flex items-center gap-2 py-1">
      <Checkbox
        id={`module-${name}`}
        checked={checked}
        onCheckedChange={() => onToggle(name)}
      />
      <Label
        htmlFor={`module-${name}`}
        className="font-normal font-mono text-[12px] cursor-pointer"
      >
        {name}
      </Label>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ScanLaunchDialog
// ---------------------------------------------------------------------------

export function ScanLaunchDialog({
  projectId,
  isOpen,
  onClose,
  project,
  userCanLaunchActive,
  onLaunched,
}: ScanLaunchDialogProps) {
  const [mode, setMode] = useState<ScanMode>("passive");
  const [safelist, setSafelist] = useState<EASMSafelist | null>(null);
  const [safelistError, setSafelistError] = useState(false);
  const [checkedModules, setCheckedModules] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  const disabledReason = activeDisabledReason(project, userCanLaunchActive);
  const activeDisabled = disabledReason !== null;

  // -----------------------------------------------------------------------
  // Load safelist on dialog open
  // -----------------------------------------------------------------------
  useEffect(() => {
    if (!isOpen) return;
    setSafelist(null);
    setSafelistError(false);
    setMode("passive");

    getSafelist()
      .then((s) => {
        setSafelist(s);
        setCheckedModules(new Set(s.modules));
      })
      .catch(() => {
        setSafelistError(true);
      });
  }, [isOpen]);

  // -----------------------------------------------------------------------
  // Module toggle
  // -----------------------------------------------------------------------
  function toggleModule(name: string) {
    setCheckedModules((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  }

  // -----------------------------------------------------------------------
  // Submit handler
  // -----------------------------------------------------------------------
  async function handleSubmit() {
    if (submitting || checkedModules.size === 0) return;
    setSubmitting(true);
    try {
      await launchScan(projectId, {
        scan_mode: mode,
        modules: Array.from(checkedModules),
      });
      toast.success("Scan launched successfully.");
      onLaunched?.();
      onClose();
    } catch (err) {
      const status =
        err && typeof err === "object" && "status" in err
          ? (err as { status?: number }).status
          : undefined;
      const msg = err instanceof Error ? err.message : "";

      if (status === 403) {
        if (msg.toLowerCase().includes("expired") || msg.toLowerCase().includes("expir")) {
          toast.error(
            "Active-scan authorisation has expired. Re-confirm on the Settings tab.",
          );
        } else {
          toast.error(
            "Active-scan authorisation is not set. Set it on the Settings tab before launching an active scan.",
          );
        }
      } else if (status === 422) {
        // Extract invalid module names from detail if present
        const names = msg.replace(/^.*?:/, "").trim();
        toast.error(
          `One or more selected modules are not in the stable safelist: ${names}. Remove them and retry.`,
        );
      } else if (status === 503) {
        toast.error(
          "Scan limit reached. Wait for a running scan to finish before launching another.",
        );
      } else {
        toast.error(`Failed to launch scan. ${msg}`);
      }
    } finally {
      setSubmitting(false);
    }
  }

  // -----------------------------------------------------------------------
  // Derived state
  // -----------------------------------------------------------------------
  const submitLabel = submitting
    ? "Launching…"
    : mode === "passive"
      ? "Launch passive scan"
      : "Launch active scan";

  const submitDisabled = submitting || checkedModules.size === 0;

  const hasShodan = safelist?.modules.includes("shodan_dns") ?? false;

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  return (
    <Dialog
      open={isOpen}
      onOpenChange={(v) => {
        if (!v && !submitting) onClose();
      }}
    >
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Launch EASM Scan</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Body paragraph */}
          <p className="text-sm text-muted-foreground leading-[1.7]">
            Scan targets derive from this project&apos;s active-test scope rows.
            Passive scans are safe to run without written authorisation.
          </p>

          {/* Mode radio */}
          <div className="space-y-2">
            <Label>Mode</Label>
            <RadioGroup
              value={mode}
              onValueChange={(v) => setMode(v as ScanMode)}
              className="gap-3"
            >
              {/* Passive */}
              <div className="flex items-start gap-2">
                <RadioGroupItem value="passive" id="mode-passive" className="mt-0.5" />
                <div className="space-y-0.5">
                  <Label htmlFor="mode-passive" className="font-medium cursor-pointer">
                    Passive
                  </Label>
                  <p className="text-xs text-muted-foreground leading-[1.5]">
                    Safe reconnaissance using passive modules only. No direct
                    contact with target systems.
                  </p>
                </div>
              </div>

              {/* Active */}
              <div className="flex items-start gap-2">
                <RadioGroupItem
                  value="active"
                  id="mode-active"
                  disabled={activeDisabled}
                  className="mt-0.5"
                />
                <div className="space-y-0.5">
                  {activeDisabled ? (
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Label
                            htmlFor="mode-active"
                            className="font-medium text-muted-foreground cursor-not-allowed"
                          >
                            Active
                          </Label>
                        </TooltipTrigger>
                        <TooltipContent>
                          {disabledReason}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  ) : (
                    <Label htmlFor="mode-active" className="font-medium cursor-pointer">
                      Active
                    </Label>
                  )}
                  <p className="text-xs text-muted-foreground leading-[1.5]">
                    {activeDisabled
                      ? disabledReason
                      : "Active reconnaissance permitted by scope authorisation. BBOT sends requests directly to targets."}
                  </p>
                </div>
              </div>
            </RadioGroup>
          </div>

          {/* Module multi-select */}
          <div className="space-y-2">
            <Label>Modules</Label>
            {safelistError ? (
              <p className="text-sm text-destructive">
                Could not load modules. Close and try again.
              </p>
            ) : safelist === null ? (
              /* Loading skeleton */
              <div className="rounded-md border border-border p-2 space-y-1.5">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-5 bg-card/60 rounded animate-pulse"
                  />
                ))}
              </div>
            ) : (
              <ScrollArea className="h-[200px] rounded-md border border-border px-3 py-2">
                {safelist.modules.map((mod) => (
                  <ModuleItem
                    key={mod}
                    name={mod}
                    checked={checkedModules.has(mod)}
                    onToggle={toggleModule}
                  />
                ))}
              </ScrollArea>
            )}

            {/* Shodan optional note */}
            {hasShodan && (
              <p className="text-xs text-muted-foreground leading-[1.5]">
                Shodan API key optional — enables shodan_dns. Without it,
                shodan_dns is skipped and the scan continues.
              </p>
            )}
          </div>

          {/* Confirm copy */}
          <p className="text-sm text-muted-foreground leading-[1.7]">
            This will run a BBOT scan against this project&apos;s active-test
            scope. Continue?
          </p>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={onClose}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            variant="default"
            onClick={handleSubmit}
            disabled={submitDisabled}
          >
            {submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
