"use client";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { type Tier, TIER_COLORS } from "@/lib/scoring";

// ---------------------------------------------------------------------------
// TierBadge — S/A/B/C/D pill matching UI-SPEC §Surface 1 colour map.
//
// Shape: inline-flex items-center h-4 px-2 border-l-2 rounded-sm brand-caption
// Mirrors BrandProvenanceBadge shape from Phase 12.
// ---------------------------------------------------------------------------

type TierBadgeProps = {
  tier: Tier;
  className?: string;
  /** When provided, wraps the badge in a shadcn Tooltip. */
  tooltip?: string;
};

function TierPill({ tier, className }: { tier: Tier; className?: string }) {
  const colors = TIER_COLORS[tier];
  return (
    <span
      className={cn(
        "inline-flex items-center h-4 px-2 border-l-2 rounded-sm brand-caption",
        colors.bg,
        colors.text,
        colors.border,
        className,
      )}
    >
      {tier}
    </span>
  );
}

export function TierBadge({ tier, className, tooltip }: TierBadgeProps) {
  if (!tooltip) {
    return <TierPill tier={tier} className={className} />;
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <TierPill tier={tier} className={className} />
        </TooltipTrigger>
        <TooltipContent>{tooltip}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
