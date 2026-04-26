"use client";

/**
 * CompletionBadge — per-section completeness badge for the TIBER left sidebar.
 * Phase 18 plan 18-06. UI-SPEC §"Section Completeness Badge Colour Map".
 *
 * States:
 *   complete   — green CheckCircle2, bg-green-500/15 text-green-300
 *   incomplete — red XCircle, bg-red-500/15 text-red-300; tooltip lists missing fields
 *   not-started — muted Circle (empty), bg-muted text-muted-foreground
 */

import { CheckCircle2, Circle, XCircle } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export type CompletionState = "complete" | "incomplete" | "not-started";

interface CompletionBadgeProps {
  state: CompletionState;
  /** List of missing field names (shown in tooltip when state === "incomplete"). */
  missingFields?: string[];
}

export function CompletionBadge({ state, missingFields = [] }: CompletionBadgeProps) {
  if (state === "complete") {
    return (
      <span className="inline-flex items-center gap-1 rounded-sm border px-1.5 brand-caption bg-green-500/15 text-green-300 border-green-700">
        <CheckCircle2 size={12} />
      </span>
    );
  }

  if (state === "incomplete") {
    const tooltipContent =
      missingFields.length > 0
        ? `Missing: ${missingFields.join(", ")}`
        : "Section incomplete";

    return (
      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex items-center gap-1 rounded-sm border px-1.5 brand-caption bg-red-500/15 text-red-300 border-red-600 cursor-help">
              <XCircle size={12} />
            </span>
          </TooltipTrigger>
          <TooltipContent side="right" className="text-xs max-w-48">
            {tooltipContent}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  // not-started
  return (
    <span className="inline-flex items-center gap-1 rounded-sm border px-1.5 brand-caption bg-muted text-muted-foreground border-muted-foreground/40">
      <Circle size={12} />
    </span>
  );
}
