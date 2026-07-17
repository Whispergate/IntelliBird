"use client";

/**
 * AISuggestionChip
 * UI-SPEC §Surface 1c — pending/confirmed/discarded suggestion chip.
 *
 * Optimistic confirm/discard: chip visual state updates immediately.
 * On API error the chip reverts to its previous state with a toast.
 */

import { Check, X, CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export type SuggestionStatus = "pending" | "confirmed" | "discarded";

export interface AISuggestion {
  id: string;
  entity_value: string;
  entity_type: "cve" | "attack" | "actor";
  status: SuggestionStatus;
}

export function AISuggestionChip({
  suggestion,
  onChange,
}: {
  suggestion: AISuggestion;
  onChange?: (next: SuggestionStatus) => void;
}) {
  const [status, setStatus] = useState<SuggestionStatus>(suggestion.status);

  async function transition(next: "confirmed" | "discarded") {
    const prev = status;
    setStatus(next); // optimistic
    try {
      const path = next === "confirmed" ? "confirm" : "discard";
      const r = await fetch(`/api/ai/suggestions/${suggestion.id}/${path}`, {
        method: "POST",
      });
      if (!r.ok) throw new Error(String(r.status));
      onChange?.(next);
    } catch {
      setStatus(prev); // revert
      toast.error(
        next === "confirmed"
          ? "Could not confirm suggestion."
          : "Could not discard suggestion.",
      );
    }
  }

  // Chip class variants per UI-SPEC §1c
  const baseChip =
    "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs";

  if (status === "confirmed") {
    return (
      <div
        className={`${baseChip} bg-green-500/10 text-green-300 border-green-700`}
        data-testid="suggestion-chip"
        data-status="confirmed"
      >
        <span className="font-mono">{suggestion.entity_value}</span>
        <span className="brand-caption text-muted-foreground ml-1">
          {suggestion.entity_type}
        </span>
        <CheckCircle2 size={12} className="text-green-400 ml-1" />
      </div>
    );
  }

  if (status === "discarded") {
    return (
      <div
        className={`${baseChip} bg-muted text-muted-foreground border-muted-foreground/40`}
        data-testid="suggestion-chip"
        data-status="discarded"
      >
        <span className="font-mono">{suggestion.entity_value}</span>
        <span className="brand-caption text-muted-foreground ml-1">
          {suggestion.entity_type}
        </span>
        <X size={12} className="text-muted-foreground/60 ml-1" />
      </div>
    );
  }

  // pending state
  return (
    <div
      className={`${baseChip} bg-yellow-500/10 text-yellow-300 border-yellow-600`}
      data-testid="suggestion-chip"
      data-status="pending"
    >
      <span className="font-mono">{suggestion.entity_value}</span>
      <span className="brand-caption text-muted-foreground ml-1">
        {suggestion.entity_type}
      </span>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              aria-label="Confirm suggestion"
              className="ml-1 text-green-400 hover:text-green-200"
              onClick={() => transition("confirmed")}
            >
              <Check size={12} />
            </button>
          </TooltipTrigger>
          <TooltipContent side="top">
            <p>Confirm</p>
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              aria-label="Discard suggestion"
              className="text-muted-foreground hover:text-destructive"
              onClick={() => transition("discarded")}
            >
              <X size={12} />
            </button>
          </TooltipTrigger>
          <TooltipContent side="top">
            <p>Discard</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}
