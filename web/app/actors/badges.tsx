"use client";
import { cn } from "@/lib/utils";

const SOPHISTICATION_STYLES: Record<string, string> = {
  minimal:      "bg-muted text-muted-foreground",
  intermediate: "bg-teal-900/40 text-teal-300",
  advanced:     "bg-[var(--brand-signal)]/20 text-[var(--brand-signal)]",
  expert:       "bg-destructive/15 text-red-400",
};

export function SophisticationBadge({ value }: { value: string | null }) {
  const style = value ? SOPHISTICATION_STYLES[value.toLowerCase()] : undefined;
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-1 rounded-sm border text-[12px] font-medium uppercase tracking-wide",
        style ?? "bg-muted text-muted-foreground italic",
      )}
    >
      {value ?? "Unknown"}
    </span>
  );
}

export function CampaignScopeBadge({
  projectId,
  projectName,
}: {
  projectId: string | null;
  projectName?: string;
}) {
  if (!projectId) {
    return (
      <span className="inline-flex items-center px-2 py-1 rounded-sm border text-[12px] font-medium uppercase tracking-wide bg-[var(--brand-signal)]/15 text-[var(--brand-signal)] border-[var(--brand-signal)]/40">
        Global
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-2 py-1 rounded-sm border text-[12px] font-medium uppercase tracking-wide bg-teal-900/40 text-teal-300 border-teal-700">
      {projectName ?? "Project"}
    </span>
  );
}
